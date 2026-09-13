# routes/batch_scan.py

import os
import logging
import shutil
from datetime import datetime
from typing import List
from fastapi import APIRouter, UploadFile, File, Form, Depends
from bson import ObjectId

from db import require_db
from routes.auth import get_current_user
from services.image_preprocessor import ImagePreprocessor
from services.ocr_service import OCRService
from services.field_extractor import FieldExtractor
from services.rule_engine import RuleEngine
from services.font_analyzer import font_analyzer, get_image_dimensions
from services.box_mapper import map_field_boxes
from services.cloudinary_service import upload_image

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scan", tags=["batch-scan"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

preprocessor = ImagePreprocessor()
ocr_service = OCRService()
field_extractor = FieldExtractor()
rule_engine = RuleEngine()


def _process_single(file_path: str):
    preprocessed_path = preprocessor.preprocess(file_path)
    ocr_result = ocr_service.extract_text(preprocessed_path)
    extracted_fields = field_extractor.extract_all(ocr_result["full_text"])

    font_analysis_result = {}
    try:
        img_w, img_h = get_image_dimensions(preprocessed_path)
        font_analysis_result = font_analyzer.analyze(
            ocr_result.get("word_boxes", []), img_w, img_h)
    except Exception as e:
        logger.warning(f"Font analysis failed: {e}")

    validation_result = rule_engine.validate(extracted_fields, font_analysis_result)

    field_boxes = {}
    try:
        import cv2
        img = cv2.imread(preprocessed_path)
        if img is not None:
            h, w = img.shape[:2]
            field_boxes = map_field_boxes(
                extracted_fields, ocr_result.get("word_boxes", []), w, h)
    except Exception as e:
        logger.warning(f"Could not compute field boxes: {e}")

    return extracted_fields, validation_result, font_analysis_result, field_boxes, ocr_result


@router.post("/batch")
def batch_scan(
    files: List[UploadFile] = File(...),
    lat: float = Form(None),
    lng: float = Form(None),
    current_user=Depends(get_current_user),
):
    db = require_db()
    location = {"lat": lat, "lng": lng} if lat is not None and lng is not None else None
    results = []

    for file in files:
        filename = f"{datetime.utcnow().timestamp()}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        try:
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            extracted_fields, validation_result, font_analysis, field_boxes, ocr_result = \
                _process_single(file_path)

            # Upload to Cloudinary (falls back to local path if not configured)
            cloudinary_url = upload_image(file_path)

            scan_doc = {
                "product_id": None,
                "image_url": cloudinary_url or file_path,
                "source": "batch",
                "ecommerce_url": None,
                "ocr_raw_text": ocr_result["full_text"],
                "extracted_fields": extracted_fields,
                "field_boxes": field_boxes,
                "font_analysis": font_analysis,
                "overall_status": validation_result["overall_status"],
                "violations": [],
                "violations_summary": {
                    "total": validation_result["summary"]["failed"],
                    "critical": validation_result["summary"]["critical"],
                    "major": validation_result["summary"]["major"],
                    "minor": validation_result["summary"]["minor"],
                    "needs_review": validation_result["summary"]["needs_review"],
                },
                "location": location,
                "ocr_engine": ocr_result.get("engine", "unknown"),
                "confidence": ocr_result["confidence"],
                "synced": True,
                "scanned_by": current_user["_id"],
                "scanned_at": datetime.utcnow(),
            }
            scan_result = db.scans.insert_one(scan_doc)
            scan_id = scan_result.inserted_id

            violation_ids = []
            for v in validation_result["violations"]:
                vdoc = {
                    "scan_id": scan_id,
                    "product_id": None,
                    "rule_id": v["rule_id"],
                    "rule_section": v.get("rule_section", ""),
                    "field": v["field"],
                    "severity": v["severity"],
                    "status": v["status"],
                    "message": v["message"],
                    "suggestion": v.get("suggestion", ""),
                    "resolution_status": "pending",
                    "assigned_to": None,
                    "due_date": None,
                    "resolution_notes": None,
                    "resolved_at": None,
                    "created_at": datetime.utcnow(),
                }
                vres = db.violations.insert_one(vdoc)
                violation_ids.append(vres.inserted_id)

            db.scans.update_one({"_id": scan_id}, {"$set": {"violations": violation_ids}})

            results.append({
                "filename": file.filename,
                "scan_id": str(scan_id),
                "status": validation_result["overall_status"],
                "violations_count": len(validation_result["violations"]),
                "product_name": extracted_fields.get("commodity_name", "Unknown"),
            })
        except Exception as e:
            logger.error(f"Batch scan failed for {file.filename}: {e}")
            results.append({
                "filename": file.filename,
                "scan_id": None,
                "status": "error",
                "violations_count": 0,
                "product_name": None,
                "error": str(e),
            })

    total = len(results)
    successful = len([r for r in results if r["status"] != "error"])
    compliant = len([r for r in results if r["status"] == "compliant"])

    return {
        "total": total,
        "successful": successful,
        "compliant": compliant,
        "non_compliant": successful - compliant,
        "results": results,
    }
