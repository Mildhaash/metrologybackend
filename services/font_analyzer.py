# services/font_analyzer.py

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_DPI = 300


class FontAnalyzer:
    def __init__(self, dpi: int = DEFAULT_DPI):
        self.dpi = dpi

    def analyze(
        self,
        word_boxes: List[Dict],
        image_width_px: int = 0,
        image_height_px: int = 0,
    ) -> Dict:
        if not word_boxes:
            return {"panel_area_cm2": 0, "detected_font_heights": []}

        px_per_mm = self.dpi / 25.4

        heights = []
        for wb in word_boxes:
            h_px = wb.get("height_px", 0)
            if h_px <= 0:
                continue
            h_mm = round(h_px / px_per_mm, 2)
            heights.append({
                "text": wb.get("text", ""),
                "height_mm": h_mm,
                "height_px": round(h_px, 1),
            })

        panel_area_cm2 = 0
        if image_width_px > 0 and image_height_px > 0:
            w_cm = image_width_px / (self.dpi / 2.54)
            h_cm = image_height_px / (self.dpi / 2.54)
            panel_area_cm2 = round(w_cm * h_cm, 1)

        return {
            "panel_area_cm2": panel_area_cm2,
            "detected_font_heights": heights,
            "dpi": self.dpi,
            "word_count": len(heights),
            "avg_height_mm": round(
                sum(h["height_mm"] for h in heights) / len(heights), 2
            ) if heights else 0,
            "min_height_mm": round(
                min(h["height_mm"] for h in heights), 2
            ) if heights else 0,
            "max_height_mm": round(
                max(h["height_mm"] for h in heights), 2
            ) if heights else 0,
        }


def get_image_dimensions(image_path: str) -> tuple:
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            return im.size
    except Exception:
        pass
    try:
        import cv2
        img = cv2.imread(image_path)
        if img is not None:
            h, w = img.shape[:2]
            return (w, h)
    except Exception:
        pass
    return (0, 0)


font_analyzer = FontAnalyzer()
