import logging
import base64
from rapidocr_onnxruntime import RapidOCR

logger = logging.getLogger(__name__)

class OCRService:
    def __init__(self):
        self._rapid_ocr = RapidOCR()
        self._gemini_scanner = None

    def _get_gemini_scanner(self):
        if self._gemini_scanner is None:
            try:
                from services.gemini_scanner import GeminiScanner
                self._gemini_scanner = GeminiScanner()
            except Exception as e:
                logger.warning(f"Could not initialize GeminiScanner: {e}")
                self._gemini_scanner = False
        return self._gemini_scanner if self._gemini_scanner is not False else None

    def extract_text(self, image_path: str) -> dict:
        gemini = self._get_gemini_scanner()
        if gemini:
            try:
                return self._extract_with_gemini(image_path, gemini)
            except Exception as e:
                logger.warning(f"Gemini OCR failed ({e}) — falling back to RapidOCR")

        return self._extract_with_rapidocr(image_path)

    def _extract_with_gemini(self, image_path: str, gemini) -> dict:
        import io
        with open(image_path, "rb") as f:
            content = f.read()

        image_base64 = base64.b64encode(content).decode("utf-8")

        gemini_result = gemini.scan_image_fast(image_base64)

        # Gemini bboxes are 0-1000 normalized; downstream (box_mapper)
        # expects pixel vertices for this image, so scale them up.
        img_w, img_h = 0, 0
        try:
            from PIL import Image
            with Image.open(image_path) as im:
                img_w, img_h = im.size
        except Exception:
            try:
                import cv2
                _img = cv2.imread(image_path)
                if _img is not None:
                    img_h, img_w = _img.shape[:2]
            except Exception:
                pass

        word_boxes = []
        for field in gemini_result.fields:
            if field.bbox and len(field.bbox) == 4:
                ymin, xmin, ymax, xmax = field.bbox
                # Skip empty/degenerate boxes (e.g. [0,0,0,0] when Gemini
                # omits a location) — they would map to a zero-area overlay.
                if ymax > ymin and xmax > xmin and img_w and img_h:
                    word_boxes.append({
                        "text": field.value,
                        "vertices": [
                            {"x": xmin / 1000 * img_w, "y": ymin / 1000 * img_h},
                            {"x": xmax / 1000 * img_w, "y": ymin / 1000 * img_h},
                            {"x": xmax / 1000 * img_w, "y": ymax / 1000 * img_h},
                            {"x": xmin / 1000 * img_w, "y": ymax / 1000 * img_h},
                        ],
                        "height_px": (ymax - ymin) / 1000 * img_h
                    })

        if not word_boxes:
            # Gemini gave text but no locations — fall back to RapidOCR
            # purely for box geometry (extracted text still comes from
            # Gemini). This keeps overlays working in all cases.
            try:
                rapid = self._extract_with_rapidocr(image_path)
                word_boxes = rapid.get("word_boxes", [])
            except Exception as e:
                logger.warning(f"RapidOCR geometry fallback failed: {e}")

        return {
            "full_text": gemini_result.ocr_text,
            "word_boxes": word_boxes,
            "confidence": 0.95,
            "engine": "gemini",
            "gemini_fields": [
                {"name": f.name, "value": f.value, "bbox": f.bbox}
                for f in gemini_result.fields
            ],
        }

    def _extract_with_rapidocr(self, image_path: str) -> dict:
        result, elapse = self._rapid_ocr(image_path)

        if not result:
            return {"full_text": "", "word_boxes": [], "confidence": 0, "engine": "rapidocr"}

        texts = []
        word_boxes = []
        confidences = []

        for bbox, text, conf in result:
            texts.append(text)
            confidences.append(float(conf))
            ys = [point[1] for point in bbox]
            height = max(ys) - min(ys)
            word_boxes.append({
                "text": text,
                "vertices": [{"x": p[0], "y": p[1]} for p in bbox],
                "height_px": height
            })

        return {
            "full_text": "\n".join(texts),
            "word_boxes": word_boxes,
            "confidence": sum(confidences) / len(confidences) if confidences else 0,
            "engine": "rapidocr"
        }
