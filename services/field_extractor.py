# services/field_extractor.py

import re
from typing import Optional, Dict

class FieldExtractor:
    def extract_all(self, ocr_text: str) -> Dict[str, Optional[str]]:
        return {
            "commodity_name": self._extract_commodity_name(ocr_text),
            "net_quantity": self._extract_net_quantity(ocr_text),
            "mrp": self._extract_mrp(ocr_text),
            "mrp_formatted": self._format_mrp(self._extract_mrp(ocr_text)),
            "manufacture_date": self._extract_date(ocr_text),
            "best_before": self._extract_best_before(ocr_text),
            "batch_number": self._extract_batch_number(ocr_text),
            "manufacturer_name": self._extract_manufacturer(ocr_text),
            "manufacturer_address": self._extract_address(ocr_text),
            "consumer_care_email": self._extract_email(ocr_text),
            "consumer_care_phone": self._extract_phone(ocr_text),
            "country_of_origin": self._extract_origin(ocr_text),
            "language": self._detect_language(ocr_text),
        }

    def _extract_mrp(self, text: str) -> Optional[str]:
        normalized = re.sub(r'\s*\n\s*', ' ', text)
        # Currency marker: Rs text ("Rs", "Rs.", "Re.", "INR", "Rupees")
        # as well as the ₹ symbol (U+20B9). "R[s5]" tolerates common OCR
        # misreads of "Rs" as "R5".
        currency = r"(?:R[s5]s?\.?|Re\.?|INR|\u20b9|Rupees?)"
        mrp_kw = r"(?:M\.?\s*R\.?\s*P\.?|Maximum\s+Retail\s+Price|Max\.?\s*Retail\s+Price)"
        taxes = r"(?:\(?incl\.?(?:usive)?\s+of\s+all\s*taxes?\)?)"
        patterns = [
            rf"{mrp_kw}\s*(?:{taxes})?\s*[:.\s]*{currency}?\s*[:.\s]*(\d+(?:\.\d{{1,2}})?)\s*(?:/\s*-)?\s*(?:{taxes})?",
            rf"{currency}\s*[:.\s]*(\d+(?:\.\d{{1,2}})?)\s*(?:/\s*-)?\s*(?:{taxes})?",
            rf"(\d+(?:\.\d{{1,2}})?)\s*(?:/\s*-)?\s*(?:{taxes})?\s*[:.\s]*{mrp_kw}",
            rf"{mrp_kw}\s*[:\s]*(\d+(?:\.\d{{1,2}})?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _extract_net_quantity(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:Net\s+(?:Weight|Quantity|Volume|Contents?|Qty)|Net\s+Wt\.?|Weight|Quantity)\s*[:\s]*(\d+(?:\.\d+)?)\s*(kg|g|gm|grams?|ml|litre|litres?|l|pcs?|pieces?|nos?)\b",
            r"(\d+(?:\.\d{1,5})?)\s*(kg|g|gm|grams?|ml|litre|litres?|pcs?|pieces?|nos?)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result = match.group(0)
                number = re.search(r"(\d+)", result)
                if number and len(number.group(1)) <= 8:
                    return result
        return None

    def _extract_date(self, text: str) -> Optional[str]:
        normalized = re.sub(r'\s*\n\s*', ' ', text)
        date_val = r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{1,2}[/\-\.]\d{4}|\d{1,2}[/\-\.](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s.]*(?:\d{4})|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s.]?\d{4})"
        patterns = [
            r"(?:Date\s+of\s+)?(?:Manufacture|Mfg|Production|Packed\s*On?|Packaging|Pkd\s*On?|Packedon)\.?\s*(?:Date)?\s*[:\s]*" + date_val,
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                return match.group(0)
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _extract_manufacturer(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:Manufactured?\s*(?:&|and)\s*Packed|Manufactured?|Packed?|Marketed?|Produced?)\s*(?:by|at|in)[:\s]+(.+?)(?:\n|$)",
            r"(?:Mfg|Pkd|Marketed)\s*(?:by)?[:\s]+(.+?)(?:\n|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_email(self, text: str) -> Optional[str]:
        pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        match = re.search(pattern, text)
        return match.group(0) if match else None

    def _extract_phone(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:Customer\s*Care|Consumer\s*Care|Helpline|Contact)\s*[:\s]+.*?(?:Ph\.?\s*No\.?|Phone|Tel\.?)\s*[:\s]*([\d\-\s\+]{10,})",
            r"(?:Ph\.?\s*No\.?|Phone|Tel\.?)\s*[:\s]+([\d\-\s\+]{10,})",
            r"(\+91[\-\s]?\d{10})",
            r"(1800[\-\s]?\d{3}[\-\s]?\d{3,4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result = match.group(0).strip()
                number = re.findall(r"\d", result)
                if len(number) >= 10 and len(number) <= 15:
                    return result
        return None

    def _detect_language(self, text: str) -> str:
        hindi_chars = len(re.findall(r'[\u0900-\u097F]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))

        if hindi_chars > english_chars:
            return "hindi"
        elif english_chars > 0:
            return "english"
        return "unknown"

    def _format_mrp(self, mrp_raw: Optional[str]) -> Optional[str]:
        if not mrp_raw:
            return None
        match = re.search(r"(\d+(?:\.\d{1,2})?)", mrp_raw)
        return f"₹{match.group(1)}" if match else None

    def _extract_best_before(self, text: str) -> Optional[str]:
        normalized = re.sub(r'\s*\n\s*', ' ', text)
        patterns = [
            r"(?:Best\s+Before|Use\s+by|Use\s+By|Expiry|EXP|Exp\.?)\s*[:\s]+(\d+)\s*(months?|days?|years?)",
            r"(?:Best\s+Before|Use\s+by|Use\s+By|Expiry|EXP|Exp\.?)\s*[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
            r"(?:Best\s+Before|Use\s+by|Use\s+By|Expiry|EXP|Exp\.?)\s*[:\s]+(\d{1,2}[/\-\.]\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                return match.group(0)
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _extract_batch_number(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:Batch|Lot|Serial)\s*(?:No\.?|Number|#)\s*[:\s]+([A-Za-z0-9\-]+)",
            r"(?:B\.?\s*No\.?|Batch\.?)\s*[:\s]+([A-Za-z0-9\-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return None

    def _extract_address(self, text: str) -> Optional[str]:
        pattern = r"([A-Za-z0-9,.\-\s]{10,}?\b\d{6}\b)"
        match = re.search(pattern, text)
        return match.group(0).strip() if match else None

    def _extract_origin(self, text: str) -> Optional[str]:
        pattern = r"Country\s+of\s+Origin[:\s]+([A-Za-z\s]+?)(?:\n|$)"
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _extract_commodity_name(self, text: str) -> Optional[str]:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return lines[0] if lines else None