# services/gemini_scanner.py

import os
import json
import logging
import base64
from typing import List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DetectedField(BaseModel):
    name: str
    value: str
    bbox: List[int] = Field(description="Bounding box [ymin, xmin, ymax, xmax] normalized to 0-1000")


class GeminiScanResult(BaseModel):
    ocr_text: str
    fields: List[DetectedField]


class GeminiScanner:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        from google import genai
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-3.6-flash"

    @staticmethod
    def _resize_image(image_base64: str, max_dim: int = 1024) -> str:
        """Resize base64 image to max_dim to speed up Gemini API calls."""
        try:
            from PIL import Image
            import io
            image_data = base64.b64decode(image_base64)
            img = Image.open(io.BytesIO(image_data))
            w, h = img.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.warning(f"Image resize failed, using original: {e}")
        return image_base64

    def scan_image(self, image_base64: str, mime_type: str = "image/jpeg") -> GeminiScanResult:
        prompt = (
            "Analyze this product label image.\n\n"
            "Step 1: Extract ALL visible text from the label (OCR).\n"
            "Step 2: Find these specific fields and their bounding boxes:\n"
            "- MRP (Maximum Retail Price) - look for MRP, M.R.P., Rs., Rs, ₹ (Rs symbol), INR, Rupees\n"
            "- manufacture_date (Manufacturing/Packing Date) - look for Mfg, Manufactured, Packed On, Mfd\n"
            "- net_quantity (Net Quantity/Weight) - look for Net Weight, Net Quantity, Net Qty, Weight, Volume\n"
            "- best_before (Expiry/Best Before Date) - look for Exp, Expiry, Best Before, Use By\n\n"
            "Return ONLY valid JSON, no markdown, no explanation:\n"
            '{"ocr_text": "all text visible on the label", '
            '"fields": ['
            '{"name": "mrp", "value": "MRP Rs.199", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "manufacture_date", "value": "01/2025", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "net_quantity", "value": "500g", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "best_before", "value": "12/2026", "bbox": [ymin, xmin, ymax, xmax]}'
            "]}\n\n"
            "bbox values are integers 0-1000, normalized to image dimensions.\n"
            "If a field is not found, omit it from the fields array.\n"
            "IMPORTANT: Use exact field names: mrp, manufacture_date, net_quantity, best_before\n"
            "IMPORTANT: For mrp, include the FULL declaration with the MRP/M.R.P. prefix "\
            "and the currency marker exactly as printed (Rs, Rs., ₹, INR)."
        )

        try:
            from google.genai import types

            image_base64 = self._resize_image(image_base64)
            image_data = base64.b64decode(image_base64)

            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=image_data, mime_type=mime_type),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                )
            )

            result_text = response.text.strip()

            # Strip markdown code fences if present
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1]
                if result_text.endswith("```"):
                    result_text = result_text[:-3]
                result_text = result_text.strip()

            logger.info(f"Gemini response length: {len(result_text)}")
            logger.debug(f"Gemini response preview: {result_text[:300]}")

            result_json = json.loads(result_text)

            fields = []
            FIELD_NAME_MAP = {
                "mfg_date": "manufacture_date",
                "manufacturing_date": "manufacture_date",
                "mfg": "manufacture_date",
                "date_of_mfg": "manufacture_date",
                "packed_date": "manufacture_date",
                "expiry_date": "best_before",
                "exp_date": "best_before",
                "expiration_date": "best_before",
                "qty": "net_quantity",
                "net_weight": "net_quantity",
                "net_vol": "net_quantity",
                "net_volume": "net_quantity",
                "weight": "net_quantity",
                "quantity": "net_quantity",
                "product_name": "commodity_name",
                "batch_no": "batch_number",
            }
            for f in result_json.get("fields", []):
                raw_name = f["name"].lower().strip()
                normalized_name = FIELD_NAME_MAP.get(raw_name, raw_name)
                bbox = f.get("bbox", [0, 0, 0, 0])
                if isinstance(bbox, list) and len(bbox) == 4:
                    bbox = [int(v) for v in bbox]
                else:
                    bbox = [0, 0, 0, 0]
                fields.append(DetectedField(
                    name=normalized_name,
                    value=f["value"],
                    bbox=bbox
                ))

            return GeminiScanResult(
                ocr_text=result_json.get("ocr_text", ""),
                fields=fields
            )

        except json.JSONDecodeError as e:
            logger.error(f"Gemini returned invalid JSON: {e}")
            logger.error(f"Raw response: {result_text[:500]}")
            # Return whatever text was extracted even if JSON parsing failed
            return GeminiScanResult(ocr_text=result_text, fields=[])
        except Exception as e:
            logger.error(f"Gemini scan failed: {e}")
            raise

    def scan_image_fast(self, image_base64: str, mime_type: str = "image/jpeg") -> GeminiScanResult:
        """Fast scan: OCR text + field extraction with bounding boxes."""
        prompt = (
            "Extract text and key fields from this product label.\n\n"
            "Return ONLY valid JSON, no markdown:\n"
            '{"ocr_text": "all visible text", '
            '"fields": ['
            '{"name": "mrp", "value": "the FULL MRP declaration incl. MRP/M.R.P. prefix and Rs/₹ as printed (e.g. M.R.P. : ₹120.00)", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "manufacture_date", "value": "the manufacturing date", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "net_quantity", "value": "the net quantity with unit", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "commodity_name", "value": "product name", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "manufacturer_name", "value": "manufacturer/marketer name", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "consumer_care_phone", "value": "consumer care phone", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "consumer_care_email", "value": "consumer care email", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "best_before", "value": "best before/expiry", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "country_of_origin", "value": "country of origin", "bbox": [ymin, xmin, ymax, xmax]}, '
            '{"name": "batch_number", "value": "batch no", "bbox": [ymin, xmin, ymax, xmax]}'
            "]}\n\n"
            "bbox values are integers 0-1000, normalized to image dimensions, "
            "tightly around the field value text.\n"
            "Use exact field names. Omit fields not found. Keep values short."
        )

        try:
            from google.genai import types

            image_base64 = self._resize_image(image_base64)
            image_data = base64.b64decode(image_base64)

            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=image_data, mime_type=mime_type),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                )
            )

            result_text = response.text.strip()

            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1]
                if result_text.endswith("```"):
                    result_text = result_text[:-3]
                result_text = result_text.strip()

            result_json = json.loads(result_text)

            fields = []
            FIELD_NAME_MAP = {
                "mfg_date": "manufacture_date",
                "manufacturing_date": "manufacture_date",
                "mfg": "manufacture_date",
                "date_of_mfg": "manufacture_date",
                "packed_date": "manufacture_date",
                "expiry_date": "best_before",
                "exp_date": "best_before",
                "expiration_date": "best_before",
                "qty": "net_quantity",
                "net_weight": "net_quantity",
                "net_vol": "net_quantity",
                "net_volume": "net_quantity",
                "weight": "net_quantity",
                "quantity": "net_quantity",
                "product_name": "commodity_name",
                "batch_no": "batch_number",
            }
            for f in result_json.get("fields", []):
                raw_name = f["name"].lower().strip()
                normalized_name = FIELD_NAME_MAP.get(raw_name, raw_name)
                bbox = f.get("bbox", [0, 0, 0, 0])
                if isinstance(bbox, list) and len(bbox) == 4:
                    try:
                        bbox = [int(v) for v in bbox]
                    except (TypeError, ValueError):
                        bbox = [0, 0, 0, 0]
                else:
                    bbox = [0, 0, 0, 0]
                fields.append(DetectedField(
                    name=normalized_name,
                    value=f["value"],
                    bbox=bbox,
                ))

            return GeminiScanResult(
                ocr_text=result_json.get("ocr_text", ""),
                fields=fields,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Gemini fast scan returned invalid JSON: {e}")
            return GeminiScanResult(ocr_text=result_text if 'result_text' in dir() else "", fields=[])
        except Exception as e:
            logger.error(f"Gemini fast scan failed: {e}")
            raise
