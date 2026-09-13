# routes/scan.py

import os
import base64
import logging
import tempfile
import shutil
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from bson import ObjectId
from typing import List

from db import require_db
from routes.auth import get_current_user
from services.image_preprocessor import ImagePreprocessor
from services.ocr_service import OCRService
from services.field_extractor import FieldExtractor
from services.rule_engine import RuleEngine
from services.box_mapper import map_field_boxes
from services.font_analyzer import font_analyzer, get_image_dimensions
from services.geocoding import get_short_address
from services.cloudinary_service import upload_image, upload_base64, is_configured as cloudinary_configured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scan", tags=["scan"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

preprocessor = ImagePreprocessor()
ocr_service = OCRService()
field_extractor = FieldExtractor()
rule_engine = RuleEngine()

_gemini_scanner = None


def get_gemini_scanner():
    global _gemini_scanner
    if _gemini_scanner is None:
        try:
            from services.gemini_scanner import GeminiScanner
            _gemini_scanner = GeminiScanner()
        except Exception as e:
            logger.warning(f"Could not initialize GeminiScanner: {e}")
            _gemini_scanner = False
    return _gemini_scanner if _gemini_scanner is not False else None


CRITICAL_RULE_IDS = [
    "LM-PC-2011-R6-1c",
    "LM-PC-2011-R6-1d",
    "LM-PC-2011-R6-1e",
]


class RealtimeScanRequest(BaseModel):
    image: str
    lat: float = None
    lng: float = None


def _run_realtime_pipeline(image_base64: str):
    """Run the scan pipeline: try Gemini first, fallback to RapidOCR."""
    gemini = get_gemini_scanner()
    gemini_result = None

    if gemini:
        try:
            gemini_result = gemini.scan_image_fast(image_base64)
        except Exception as e:
            logger.warning(f"Gemini scan failed: {e} — falling back to RapidOCR")

    if gemini_result:
        extracted_fields = field_extractor.extract_all(gemini_result.ocr_text)
        field_bboxes = {}
        for f in gemini_result.fields:
            field_bboxes[f.name] = {
                "value": f.value,
                "bbox": f.bbox,
            }
        ocr_text = gemini_result.ocr_text
    else:
        try:
            img_bytes = base64.b64decode(image_base64)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, dir=UPLOAD_DIR) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name

            ocr_result = ocr_service.extract_text(tmp_path)
            extracted_fields = field_extractor.extract_all(ocr_result["full_text"])
            field_bboxes = {}
            ocr_text = ocr_result["full_text"]

            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        except Exception as e:
            logger.error(f"RapidOCR fallback also failed: {e}")
            extracted_fields = {
                "commodity_name": None,
                "net_quantity": None,
                "mrp": None,
                "manufacture_date": None,
            }
            field_bboxes = {}
            ocr_text = ""

    all_validation = rule_engine.validate(extracted_fields)
    critical_violations = [v for v in all_validation["violations"] if v["rule_id"] in CRITICAL_RULE_IDS]

    ar_fields = []
    critical_field_map = {
        "mrp": "mrp",
        "manufacture_date": "manufacture_date",
        "net_quantity": "net_quantity",
    }

    for field_name, rule_field in critical_field_map.items():
        bbox_data = field_bboxes.get(field_name)
        bbox = bbox_data["bbox"] if bbox_data else None
        value = bbox_data["value"] if bbox_data else extracted_fields.get(rule_field)

        matching_violations = [v for v in critical_violations if v["field"] == rule_field]
        if matching_violations:
            status = "violation"
            message = matching_violations[0]["message"]
        elif value:
            status = "compliant"
            message = "OK"
        else:
            status = "violation"
            message = "Field not detected"

        ar_fields.append({
            "name": field_name,
            "value": value,
            "bbox": bbox,
            "status": status,
            "message": message,
        })

    return {
        "ocr_text": ocr_text,
        "extracted_fields": extracted_fields,
        "ar_fields": ar_fields,
        "overall_status": "compliant" if not critical_violations else "non-compliant",
        "violations": critical_violations,
    }


@router.post("/upload")
def upload_scan(
    file: UploadFile = File(...),
    lat: float = Form(None),
    lng: float = Form(None),
    current_user = Depends(get_current_user)
):
    db = require_db()

    filename = f"{datetime.utcnow().timestamp()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    preprocessed_path = preprocessor.preprocess(file_path)
    ocr_result = ocr_service.extract_text(preprocessed_path)
    extracted_fields = field_extractor.extract_all(ocr_result["full_text"])

    # Map each extracted value back to its location on the label so the
    # frontend can draw pass/fail overlay boxes (0-1000 normalized coords).
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

    font_analysis_result = {}
    try:
        img_w, img_h = get_image_dimensions(preprocessed_path)
        font_analysis_result = font_analyzer.analyze(
            ocr_result.get("word_boxes", []), img_w, img_h)
    except Exception as e:
        logger.warning(f"Font analysis failed: {e}")

    validation_result = rule_engine.validate(extracted_fields, font_analysis_result)

    # Upload to Cloudinary (falls back to local path if not configured)
    image_url = upload_image(file_path)

    scan_doc = {
        "product_id": None,
        "image_url": image_url or file_path,
        "source": "upload",
        "ecommerce_url": None,
        "ocr_raw_text": ocr_result["full_text"],
        "extracted_fields": extracted_fields,
        "field_boxes": field_boxes,
        "font_analysis": font_analysis_result,
        "overall_status": validation_result["overall_status"],
        "violations": [],
        "violations_summary": {
            "total": validation_result["summary"]["failed"],
            "critical": validation_result["summary"]["critical"],
            "major": validation_result["summary"]["major"],
            "minor": validation_result["summary"]["minor"],
            "needs_review": validation_result["summary"]["needs_review"],
            "total_checks": validation_result["summary"]["total_checks"],
            "passed": validation_result["summary"]["passed"],
        },
        "location": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
        "address": get_short_address(lat, lng) if lat is not None and lng is not None else None,
        "ocr_engine": ocr_result.get("engine", "google-vision"),
        "confidence": ocr_result["confidence"],
        "synced": True,
        "scanned_by": current_user["_id"],
        "scanned_at": datetime.utcnow(),
    }
    scan_result = db.scans.insert_one(scan_doc)
    scan_id = scan_result.inserted_id

    violation_ids = []
    for v in validation_result["violations"]:
        violation_doc = {
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
        vres = db.violations.insert_one(violation_doc)
        violation_ids.append(vres.inserted_id)

    db.scans.update_one({"_id": scan_id}, {"$set": {"violations": violation_ids}})

    return {
        "scan_id": str(scan_id),
        "status": validation_result["overall_status"],
        "violations": validation_result["violations"],
    }


@router.post("/realtime")
def realtime_scan(req: RealtimeScanRequest):
    try:
        result = _run_realtime_pipeline(req.image)
        if req.lat is not None and req.lng is not None:
            result["location"] = {"lat": req.lat, "lng": req.lng}

        db = require_db()

        # Upload base64 image to Cloudinary (falls back to local file if not configured)
        image_url = None
        try:
            image_url = upload_base64(req.image)
            if not image_url:
                # Fallback: save to local filesystem
                img_bytes = base64.b64decode(req.image)
                filename = f"{datetime.utcnow().timestamp()}_realtime.jpg"
                file_path = os.path.join(UPLOAD_DIR, filename)
                with open(file_path, "wb") as f:
                    f.write(img_bytes)
                image_url = file_path
        except Exception as e:
            logger.warning(f"Could not upload realtime image: {e}")

        font_analysis_result = {}
        try:
            word_boxes = result.get("word_boxes", [])
            font_analysis_result = font_analyzer.analyze(word_boxes)
        except Exception as e:
            logger.warning(f"Font analysis failed: {e}")

        all_validation = rule_engine.validate(result.get("extracted_fields", {}), font_analysis_result)

        scan_doc = {
            "product_id": None,
            "image_url": image_url,
            "source": "realtime",
            "ecommerce_url": None,
            "ocr_raw_text": result.get("ocr_text", ""),
            "extracted_fields": result.get("extracted_fields", {}),
            "field_boxes": result.get("field_bboxes", {}),
            "font_analysis": font_analysis_result,
            "overall_status": all_validation["overall_status"],
            "violations": [],
            "violations_summary": {
                "total": all_validation["summary"]["failed"],
                "critical": all_validation["summary"]["critical"],
                "major": all_validation["summary"]["major"],
                "minor": all_validation["summary"]["minor"],
                "needs_review": all_validation["summary"]["needs_review"],
                "total_checks": all_validation["summary"]["total_checks"],
                "passed": all_validation["summary"]["passed"],
            },
            "location": result.get("location"),
            "address": get_short_address(
                result.get("location", {}).get("lat"),
                result.get("location", {}).get("lng"),
            ) if result.get("location") else None,
            "ocr_engine": "google-gemini",
            "confidence": 0.9,
            "synced": True,
            "scanned_by": None,
            "scanned_at": datetime.utcnow(),
        }
        scan_result = db.scans.insert_one(scan_doc)
        scan_id = scan_result.inserted_id

        violation_ids = []
        for v in all_validation["violations"]:
            violation_doc = {
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
            vres = db.violations.insert_one(violation_doc)
            violation_ids.append(vres.inserted_id)

        db.scans.update_one({"_id": scan_id}, {"$set": {"violations": violation_ids}})

        result["scan_id"] = str(scan_id)
        return result
    except Exception as e:
        logger.error(f"Realtime scan failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/{scan_id}")
def get_scan(scan_id: str, current_user = Depends(get_current_user)):
    db = require_db()
    scan = db.scans.find_one({"_id": ObjectId(scan_id)})
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    violation_ids = scan.get("violations", [])
    violations = list(db.violations.find({"_id": {"$in": violation_ids}}))
    for v in violations:
        v["_id"] = str(v["_id"])
        v["scan_id"] = str(v["scan_id"])
        for dt_key in ("created_at", "resolved_at"):
            dt_val = v.get(dt_key)
            if dt_val is not None and not isinstance(dt_val, str):
                try:
                    v[dt_key] = dt_val.isoformat()
                except Exception:
                    v[dt_key] = str(dt_val)

    scan["_id"] = str(scan["_id"])
    scan["scanned_by"] = str(scan.get("scanned_by")) if scan.get("scanned_by") else None
    scan["violations"] = violations
    return scan


@router.get("")
def list_scans(status: str = None, limit: int = 20, offset: int = 0, current_user = Depends(get_current_user)):
    db = require_db()
    query = {}
    if status:
        query["overall_status"] = status
    scans = list(db.scans.find(query).sort("scanned_at", -1).skip(offset).limit(limit))
    for s in scans:
        s["_id"] = str(s["_id"])
        s["scanned_by"] = str(s.get("scanned_by")) if s.get("scanned_by") else None
        scanned_at = s.get("scanned_at")
        if scanned_at is not None and not isinstance(scanned_at, str):
            try:
                s["scanned_at"] = scanned_at.isoformat()
            except Exception:
                s["scanned_at"] = str(scanned_at)
        violation_ids = s.get("violations", [])
        if isinstance(violation_ids, list) and violation_ids:
            violations = list(db.violations.find({"_id": {"$in": violation_ids}}))
            for v in violations:
                v["_id"] = str(v["_id"])
                v["scan_id"] = str(v["scan_id"])
                for dt_key in ("created_at", "resolved_at"):
                    dt_val = v.get(dt_key)
                    if dt_val is not None and not isinstance(dt_val, str):
                        try:
                            v[dt_key] = dt_val.isoformat()
                        except Exception:
                            v[dt_key] = str(dt_val)
            s["violations"] = violations
        else:
            s["violations"] = []
    return {"scans": scans}


@router.delete("/{scan_id}")
def delete_scan(scan_id: str, current_user=Depends(get_current_user)):
    db = require_db()
    result = db.scans.delete_one({"_id": ObjectId(scan_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Scan not found")
    db.violations.delete_many({"scan_id": ObjectId(scan_id)})
    return {"success": True}


class ViolationResolutionRequest(BaseModel):
    resolution_status: str
    assigned_to: str = None
    due_date: str = None
    resolution_notes: str = None


@router.patch("/{scan_id}/violations/{violation_id}")
def update_violation_resolution(
    scan_id: str,
    violation_id: str,
    req: ViolationResolutionRequest,
    current_user=Depends(get_current_user)
):
    db = require_db()

    scan = db.scans.find_one({"_id": ObjectId(scan_id)})
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    update_fields = {"resolution_status": req.resolution_status}
    if req.assigned_to is not None:
        update_fields["assigned_to"] = req.assigned_to
    if req.due_date is not None:
        update_fields["due_date"] = req.due_date
    if req.resolution_notes is not None:
        update_fields["resolution_notes"] = req.resolution_notes
    if req.resolution_status == "resolved":
        update_fields["resolved_at"] = datetime.utcnow()

    result = db.violations.update_one(
        {"_id": ObjectId(violation_id), "scan_id": ObjectId(scan_id)},
        {"$set": update_fields}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Violation not found")

    return {"success": True}
