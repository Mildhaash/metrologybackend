# services/box_mapper.py
#
# Maps extracted field values back to bounding boxes on the label image.
# OCR services return per-line `word_boxes` (pixel vertices); the field
# extractor returns values that are substrings of those lines. By matching
# each value against the OCR lines we recover *where* on the label each
# declaration was found, so the frontend can draw pass/fail overlay boxes.
#
# Output coordinates are normalized to 0-1000 (x=left, y=top) so they work
# on any displayed image size without knowing pixel dimensions.

import re
from typing import Dict, List, Optional

PAD = 10  # padding added around each box, in 0-1000 units


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _clean(s: str) -> str:
    # Remove periods inside abbreviations so "M.R.P." tokenizes as "mrp".
    return re.sub(r"\.(?=[a-zA-Z])", "", s or "").lower()


def _to_1000(vertices: List[dict], img_w: int, img_h: int) -> Optional[dict]:
    if not vertices or not img_w or not img_h:
        return None
    xs = [v.get("x", 0) for v in vertices]
    ys = [v.get("y", 0) for v in vertices]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    box = {
        "x": round(x0 / img_w * 1000, 1),
        "y": round(y0 / img_h * 1000, 1),
        "width": round((x1 - x0) / img_w * 1000, 1),
        "height": round((y1 - y0) / img_h * 1000, 1),
    }
    if box["width"] <= 0 or box["height"] <= 0:
        return None
    return box


def _union(boxes: List[dict]) -> dict:
    x0 = max(0, min(b["x"] for b in boxes) - PAD)
    y0 = max(0, min(b["y"] for b in boxes) - PAD)
    x1 = min(1000, max(b["x"] + b["width"] for b in boxes) + PAD)
    y1 = min(1000, max(b["y"] + b["height"] for b in boxes) + PAD)
    return {"x": round(x0, 1), "y": round(y0, 1),
            "width": round(x1 - x0, 1), "height": round(y1 - y0, 1)}


def map_field_boxes(
    extracted_fields: Dict,
    word_boxes: List[dict],
    img_w: int,
    img_h: int,
) -> Dict[str, Optional[dict]]:
    """Return {box_key: {x, y, width, height} | None} in 0-1000 coords."""
    lines = []
    for wb in word_boxes or []:
        box = _to_1000(wb.get("vertices") or [], img_w, img_h)
        if not box:
            continue
        raw_text = wb.get("text", "")
        norm = _norm(raw_text)
        if not norm:
            continue
        lines.append({
            "norm": norm,
            "tokens": set(re.findall(r"[a-z0-9]{2,}", _clean(raw_text))),
            "box": box,
        })

    def find(value: Optional[str]) -> Optional[dict]:
        nv = _norm(value or "")
        if len(nv) < 3 or not lines:
            return None
        hits = []
        for ln in lines:
            if nv in ln["norm"] or (len(ln["norm"]) >= 4 and ln["norm"] in nv):
                hits.append(ln["box"])
        if not hits:
            # Fallback: token-overlap scoring. Handles cases where the
            # extracted value and the OCR line differ in punctuation/
            # spacing, e.g. "M.R.P. Rs. 131.35 (Incl. of all taxes)"
            # vs the Gemini field value "MRP 131.35".
            value_tokens = set(
                re.findall(r"[a-z0-9]{2,}", _clean(value)))
            if value_tokens:
                best = None
                best_score = 0
                best_shared: List[str] = []
                for ln in lines:
                    shared = [t for t in value_tokens if t in ln["tokens"]]
                    score = sum(len(t) for t in shared)
                    if score > best_score:
                        best, best_score, best_shared = ln, score, shared
                if best and (best_score >= 6
                             or any(len(t) >= 5 for t in best_shared)):
                    hits.append(best["box"])
        return _union(hits) if hits else None

    def find_union(*values: Optional[str]) -> Optional[dict]:
        """Union multiple field boxes, but prefer the largest single match
        if the boxes are too far apart (avoids stretching across the label)."""
        boxes = [b for b in (find(v) for v in values) if b]
        if not boxes:
            return None
        if len(boxes) == 1:
            return boxes[0]
        # Check if boxes are close together (overlap or within 15% of each other)
        x0_all = min(b["x"] for b in boxes)
        x1_all = max(b["x"] + b["width"] for b in boxes)
        total_span = x1_all - x0_all
        max_box_width = max(b["width"] for b in boxes)
        # If the union span is more than 2.5x the largest box, they're too far apart
        # Just use the largest box (most relevant match)
        if total_span > max_box_width * 2.5:
            return max(boxes, key=lambda b: b["width"] * b["height"])
        # Otherwise, union them
        x0 = max(0, min(b["x"] for b in boxes) - PAD)
        y0 = max(0, min(b["y"] for b in boxes) - PAD)
        x1 = min(1000, max(b["x"] + b["width"] for b in boxes) + PAD)
        y1 = min(1000, max(b["y"] + b["height"] for b in boxes) + PAD)
        return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}

    f = extracted_fields or {}
    return {
        "commodity_name": find(f.get("commodity_name")),
        "net_quantity": find(f.get("net_quantity")),
        "mrp": find(f.get("mrp")),
        "manufacture_date": find(f.get("manufacture_date")),
        "manufacturer_name": find_union(
            f.get("manufacturer_name"), f.get("manufacturer_address")),
        "consumer_care": find_union(
            f.get("consumer_care_phone"), f.get("consumer_care_email")),
        "best_before": find(f.get("best_before")),
        "country_of_origin": find(f.get("country_of_origin")),
    }
