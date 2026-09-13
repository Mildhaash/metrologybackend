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
        currency = r"(?:R[s5]s?\.?|Re\.?|INR|\u20b9|Rupees?)"
        mrp_kw = r"(?:M\.?\s*R\.?\s*P\.?|Maximum\s+Retail\s+Price|Max\.?\s*Retail\s+Price|MRP)"
        taxes = r"(?:\(?incl\.?(?:usive)?\s+of\s+all\s*taxes?\)?)"

        # Strategy 1: MRP keyword followed closely by a number
        patterns_strict = [
            # "MRP Rs. 140.00" or "M.R.P. : Rs. 140.00"
            rf"{mrp_kw}\s*[:.\s]*{currency}\s*[:.\s]*(\d+(?:\.\d{{1,2}})?)",
            # "MRP Rs (incl. of all taxes) 140.00" - number after taxes paren
            rf"{mrp_kw}\s*[:.\s]*{currency}\s*\(incl\.?\s*of\s*all\s*taxes?\)\s*[:.\s]*(\d+(?:\.\d{{1,2}})?)",
            # "MRP: (incl. of all taxes) Rs. 140.00"
            rf"{mrp_kw}\s*[:.\s]*\(incl\.?\s*of\s*all\s*taxes?\)\s*[:.\s]*{currency}?\s*[:.\s]*(\d+(?:\.\d{{1,2}})?)",
            # "MRP Rs 200.00" or "MRP: Rs. 140.00"
            rf"{mrp_kw}\s*[:.\s]*{currency}?\s*[:.\s]*(\d+(?:\.\d{{1,2}})?)\s*(?:/\s*-)?",
            # "MRP in RS. (Rs) : 165.00"
            rf"{mrp_kw}\s+in\s+{currency}\.?\s*\({currency}\)\s*[:.\s]*(\d+(?:\.\d{{1,2}})?)",
            # "MRP Rs. 60.00" (currency directly after MRP)
            rf"{mrp_kw}\s+{currency}\s*[:.\s]*(\d+(?:\.\d{{1,2}})?)",
            # "Maximum Retail Price Rs. 390.00"
            rf"{mrp_kw}\s+{currency}\s*(\d+(?:\.\d{{1,2}})?)",
            # "MAX. RETAIL PRICE: (Inclusive of all Taxes) Rs. 299.00"
            rf"{mrp_kw}\s*[:.\s]*\(?(?:Incl\.?|incl\.?)\s*(?:of\s+all\s+Taxes?)?\)?\s*[:.\s]*{currency}\s*(\d+(?:\.\d{{1,2}})?)",
        ]
        for pattern in patterns_strict:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                return match.group(0)

        # Strategy 2: Find MRP keyword, then look for next number, skip USP
        mrp_match = re.search(mrp_kw, normalized, re.IGNORECASE)
        if mrp_match:
            after_mrp = normalized[mrp_match.end():]
            # First try: find number on the same line (use original text for line detection)
            lines = text.split('\n')
            mrp_line_idx = -1
            for i, line in enumerate(lines):
                if re.search(mrp_kw, line, re.IGNORECASE):
                    mrp_line_idx = i
                    break
            if mrp_line_idx >= 0:
                mrp_line = lines[mrp_line_idx]
                same_line_match = re.search(rf"(?:{currency}\s*[:.\s]*)?(\d+(?:\.\d{{1,2}})?(?:/\s*-)?)(?:\s|$)", mrp_line)
                if same_line_match and re.search(r'\d+\.\d{2}', same_line_match.group(0)):
                    return same_line_match.group(0).strip()
            
            # Second try: look on subsequent lines, skip lines that are primarily USP
            for i in range(mrp_line_idx + 1, len(lines)) if mrp_line_idx >= 0 else []:
                line = lines[i].strip()
                if not line:
                    continue
                # Look for a price-like number on this line
                price_match = re.search(rf"(?:{currency}\s*[:.\s]*)?(\d+(?:\.\d{{1,2}})?(?:/\s*-)?)", line)
                if price_match:
                    # Check if this number is part of a USP expression (USP keyword immediately before the number)
                    num_start = price_match.start()
                    context_before_num = line[max(0, num_start-20):num_start]
                    if re.search(r'\bUSP\b', context_before_num, re.IGNORECASE):
                        continue
                    # Skip date-only lines (DD/MM/YY or DD/MM/YYYY)
                    if re.match(r'^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}$', line):
                        continue
                    # Skip lines where the number is part of a date expression (PKD, MFG, USE BY, etc.)
                    if re.search(r'(?:PKD|MFD|MFG|USE\s*BY|DATE|Packed|LOT)\s*[:.]?\s*\d', line, re.IGNORECASE):
                        continue
                    # Skip LOT/BATCH lines entirely
                    if re.search(r'(?:LOT|BATCH)\s*(?:No|NO|#|num)', line, re.IGNORECASE):
                        continue
                    # Skip if the matched number is followed by /digits (part of a date like 07/04)
                    num_text = price_match.group(0)
                    if re.match(r'^\d{1,2}[/\-]', num_text):
                        continue
                    return price_match.group(0).strip()
            
            # Third try: fallback to normalized text search
            for num_match in re.finditer(rf"(?:{currency}\s*[:.\s]*)?(\d+(?:\.\d{{1,2}})?(?:/\s*-)?)(?:\s|$)", after_mrp[:200]):
                start = max(0, num_match.start() - 30)
                context_before = after_mrp[start:num_match.start()]
                if re.search(r'\bUSP\b', context_before, re.IGNORECASE):
                    continue
                return num_match.group(0).strip()
                # Check if preceded by "USP" within 30 chars - skip if so
                start = max(0, num_match.start() - 30)
                context_before = after_mrp[start:num_match.start()]
                if re.search(r'\bUSP\b', context_before, re.IGNORECASE):
                    continue
                # Return just the currency + number portion
                return num_match.group(0).strip()

        # Strategy 3: Look for standalone number with "/-" format (e.g., "520/-" on its own line)
        for match in re.finditer(rf"(\d+(?:\.\d{{1,2}})?/\s*-)", normalized, re.IGNORECASE):
            start = max(0, match.start() - 100)
            context_before = normalized[start:match.start()]
            if re.search(mrp_kw, context_before, re.IGNORECASE):
                return match.group(0)

        # Strategy 4: Currency followed by number near MRP context
        # "Rs. 140.00" but only if MRP keyword is nearby
        for match in re.finditer(rf"{currency}\s*[:.\s]*(\d+(?:\.\d{{1,2}})?)", normalized, re.IGNORECASE):
            # Check if MRP keyword is within 100 chars before this match
            start = max(0, match.start() - 100)
            context_before = normalized[start:match.start()]
            if re.search(mrp_kw, context_before, re.IGNORECASE):
                return match.group(0)

        return None

    def _extract_net_quantity(self, text: str) -> Optional[str]:
        patterns = [
            # "Net Quantity: 200g" or "Net Wt: 200g"
            r"(?:Net\s+(?:Weight|Quantity|Volume|Contents?|Qty)|Net\s+Wt\.?)\s*[:\s]*(\d+(?:\.\d+)?)\s*(kg|g|gm|grams?|ml|litre|litres?|l|pcs?|pieces?|nos?)\b",
            # "Net Quantity: 4 N x 50 g = 200 g" or "BISCUITS NET WEIGHT: 250 g"
            r"(?:Net\s+(?:Weight|Quantity|Volume|Contents?|Qty)|Net\s+Wt\.?|BISCUITS\s+NET\s+WEIGHT)\s*[:\s]*(.+?)(?:\n|$)",
            # "Weight: 200g" or "Quantity: 200g"
            r"(?:Weight|Quantity)\s*[:\s]*(\d+(?:\.\d+)?)\s*(kg|g|gm|grams?|ml|litre|litres?|l|pcs?|pieces?|nos?)\b",
            # Standalone "NNN g" or "NNN kg" (with word boundary)
            r"\b(\d+(?:\.\d{1,5})?)\s*(kg|g|gm|grams?|ml|litre|litres?|pcs?|pieces?|nos?)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result = match.group(0)
                # For the second pattern (complex expression), extract the full quantity
                if "Net" in result or "Wt" in result or "Weight" in result or "Quantity" in result or "BISCUITS" in result:
                    return result
                number = re.search(r"(\d+)", result)
                if number and len(number.group(1)) <= 8:
                    return result
        return None

    def _extract_date(self, text: str) -> Optional[str]:
        normalized = re.sub(r'\s*\n\s*', ' ', text)
        date_val = r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{1,2}[/\-\.]\d{4}|\d{1,2}[/\-\.](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s.]*(?:\d{4})|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s.]?\d{4})"
        # BUG FIX: On? means "O + optional n". Use (?:On)? to make "On" optional.
        date_kw = r"(?:Manufacture|Mfg|Production|Packed\s*(?:On)?|Packaging|Pkd\s*(?:On)?|Packedon|MFD)"
        patterns = [
            # Explicit keywords: Manufacture, Mfg, Packed On, Pkd, Production, MFD
            r"(?:Date\s+of\s+)?" + date_kw + r"\.?\s*(?:Date)?\s*[:\s]*" + date_val,
            # "DATE OF MFG:" or "DATE OF MFD:"
            r"(?:DATE\s+OF\s+(?:MFG|MFD))\s*[:\s]*" + date_val,
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                return match.group(0)
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        
        # Fallback: "Packed On : 25OCT2025" format (day + month abbreviation + year, no separators)
        fallback_pattern = r"Packed\s*On\s*:\s*(\d{1,2}(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\d{4})"
        match = re.search(fallback_pattern, normalized, re.IGNORECASE)
        if match:
            return match.group(0)
        
        # Fallback: standalone date on its own line (for UNIBIC-style labels where dates come before keywords)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        date_pattern = re.compile(r'^(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})$')
        for line in lines:
            if date_pattern.match(line):
                return line.strip()
        
        # Fallback: date after MRP value line (HUL-style: "520/- 17/12/25 16/12/26 JK5C2")
        date_in_context = re.search(r"(?:/\s*-)\s+(\d{1,2}/\d{1,2}/\d{2,4})", normalized)
        if date_in_context:
            return date_in_context.group(1)
        
        return None

    def _extract_manufacturer(self, text: str) -> Optional[str]:
        normalized = re.sub(r'\s*\n\s*', ' ', text)
        # More permissive terminators that handle address components, parenthesized abbreviations, etc.
        address_indicators = r"(?:C-\d|[A-Z][a-z]+\s+\d|B\.?\s*No|Lic|Sector|Village|Industrial|Plot|Survey|Tower|Office|Floor|Road|Stage|Nagar|Dist|State|PIN|Pin|India|Haryana|Maharashtra|Karnataka|Gujarat|Tamil|Uttar|Madhya|Rajasthan|Andhra|Kerala|Goa|Punjab|Bihar|Jharkhand|Chhattisgarh|Odisha|West Bengal|Assam|Meghalaya|Manipur|Mizoram|Nagaland|Tripura|Sikkim|Arunachal|Uttarakhand|Himachal|Jammu|Kashmir|Delhi|Chandigarh|Puducherry)"
        terminators = rf"(?:,\s*(?:\(|[A-Za-z0-9#\-\.\s,/]+?(?:{address_indicators}))|\s*\(|\s*\d{{5,}}|\s*FSSAI|\s*$)"
        patterns = [
            # "Manufactured By: COMPANY NAME"
            r"Manufactured?\s+By\s*[:\s]+([A-Za-z][A-Za-z\s&',\.]+?)" + terminators,
            # "Manufactured For XXX By: COMPANY NAME"
            r"Manufactured\s+For\s+[\w\s]+\s+By\s*[:\s]+([A-Za-z][A-Za-z\s&',\.]+?)" + terminators,
            # "Mfd. & Mktd. by : COMPANY NAME" or "Mfd. by: COMPANY NAME"
            r"Mfd\.?\s*(?:&\s*Mktd\.?)?\s*by\s*[:\s]+([A-Za-z][A-Za-z\s&',\.]+?)" + terminators,
            # "MKTD. BY: COMPANY NAME" or "Mktd. by: COMPANY NAME"
            r"(?:MKTD|Mktd|Mkt)\.?\s*(?:BY|by)\s*[:\s]+([A-Za-z][A-Za-z\s&',\.]+?)" + terminators,
            # "Marketed by: COMPANY NAME" or "Marketd by: COMPANY NAME"
            r"Marketed?\s*by\s*[:\s]+([A-Za-z][A-Za-z\s&',\.]+?)" + terminators,
            # "Mfg. by: COMPANY NAME"
            r"(?:Mfg|Pkd|Produced?)\.?\s*by\s*[:\s]+([A-Za-z][A-Za-z\s&',\.]+?)" + terminators,
            # "Brand Owned & Marketed By: COMPANY NAME"
            r"Brand\s+Owned\s+(?:&|and)\s+Marketed\s+By\s*[:\s]+([A-Za-z][A-Za-z\s&',\.]+?)" + terminators,
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                result = match.group(1).strip()
                result = re.sub(r'[,\s]+$', '', result)
                if len(result) >= 3:
                    return result
        
        # Fallback: name before "Mfd. by:" or "Mktd. by:" keyword (e.g., "AISHANI IMPEX\nMfd. & Mktd. by :")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if re.match(r'^[A-Z][A-Z\s&\',\.]+$', line) and len(line) >= 3:
                # Check if next line contains manufacturer keyword
                if i + 1 < len(lines) and re.search(r'(?:Mfd|Mktd|Manufactured?|MKTD)\s*\.?\s*(?:by|By|BY)', lines[i + 1], re.IGNORECASE):
                    return line.strip()
        
        return None

    def _extract_email(self, text: str) -> Optional[str]:
        pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        match = re.search(pattern, text)
        return match.group(0) if match else None

    def _extract_phone(self, text: str) -> Optional[str]:
        patterns = [
            # Toll-free numbers: "TOLL FREE: 1800-10-22-221" or "TOLL FREE:1800-10-22-221"
            # More flexible digit counts to handle various toll-free formats
            r"(?:TOLL\s*FREE|Toll\s*Free)[:\s]*(1[\-\s]?800[\-\s]?\d{2,4}[\-\s]?\d{2,4}[\-\s]?\d{0,4})",
            # Generic toll-free: "1800-XX-XXXX" or "1800-XXX-XXXX"
            r"(1[\-\s]?800[\-\s]?\d{2,4}[\-\s]?\d{2,4}[\-\s]?\d{0,4})",
            # "call at +91-XX-XXXXXXXXXX"
            r"(?:call\s+at|Contact|Helpline|Phone|Tel\.?)\s*[:\s]*(\+?91[\-\s]?\d{10})",
            # "call at 0XX-XXXXXXXX" or "call at 0120-2400286"
            r"(?:call\s+at|Contact|Helpline|Phone|Tel\.?)\s*[:\s]*(\d{3,5}[\-\s]?\d{6,8})",
            # "call or email us at 78080 58080"
            r"(?:call\s+or\s+email\s+us\s+at)\s*[:\s]*(\d[\d\s]{8,12})",
            # Standard 10-digit Indian mobile with +91
            r"(\+91[\-\s]?\d{10})",
            # 10-digit starting with 6/7/8/9 (standalone word)
            r"\b([6-9]\d{9})\b",
            # Customer Care number pattern: digits after "care at" or "care no"
            r"(?:care\s+(?:at|no|number))\s*[:\s]*(\d{10,12})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result = match.group(1).strip() if match.lastindex else match.group(0).strip()
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
            # "Best Before 5 MONTHS" or "USE BY: 13/04/2027"
            r"(?:Best\s+Before|Use\s+by|Use\s+By|Expiry|EXP|Exp\.?|USE\s+BY)\s*[:\s]+(\d+)\s*(months?|days?|years?|MONTHS?|DAYS?|YEARS?)",
            # "USE BY DATE: 5 MONTHS"
            r"(?:USE\s+BY\s+DATE)\s*[:\s]+(\d+)\s*(months?|days?|years?|MONTHS?|DAYS?|YEARS?)",
            # "Best Before 13/04/2027"
            r"(?:Best\s+Before|Use\s+by|Use\s+By|Expiry|EXP|Exp\.?|USE\s+BY)\s*[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
            # "USE BY DATE: 13/04/2027"
            r"(?:USE\s+BY\s+DATE)\s*[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
            # "Best Before 13/04/27"
            r"(?:Best\s+Before|Use\s+by|Use\s+By|Expiry|EXP|Exp\.?|USE\s+BY)\s*[:\s]+(\d{1,2}[/\-\.]\d{2,4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                return match.group(0)
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        
        # Fallback: standalone date on its own line (second occurrence, for UNIBIC-style labels)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        date_pattern = re.compile(r'^(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})$')
        date_count = 0
        for line in lines:
            if date_pattern.match(line):
                date_count += 1
                if date_count == 2:
                    return line.strip()
        
        # Fallback: second date after MRP value line (HUL-style: "520/- 17/12/25 16/12/26 JK5C2")
        all_dates = re.findall(r"(?:/\s*-)\s+\d{1,2}/\d{1,2}/\d{2,4}\s+(\d{1,2}/\d{1,2}/\d{2,4})", normalized)
        if all_dates:
            return all_dates[0]
        
        return None

    def _extract_batch_number(self, text: str) -> Optional[str]:
        patterns = [
            # "BATCH NO.: DAFG28" or "Batch No.: 02-195/L1/P91/13:43"
            # Use \b to prevent matching "lot" inside "Plot"
            # Require colon as separator (not just dot) to avoid matching "Batch No. and"
            r"\b(?:Batch|Lot|Serial|LOT)\s*(?:No\.?|Number|#)\s*:\s*([A-Za-z0-9\-/:\(\)]+)",
            # "LOT No. 2042600" (no colon, digits only after space)
            r"\b(?:Batch|Lot|Serial|LOT)\s*(?:No\.?)\s+(\d{4,})",
            # "LOT NO: 8266P" or "LOT NO.: BFCJ60H"
            r"\b(?:B\.?\s*No\.?|Batch\.?\s*No\.?)\s*:\s*([A-Za-z0-9\-/:\(\)]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result = match.group(1).strip()
                # Remove trailing punctuation
                result = re.sub(r'[,\s]+$', '', result)
                if len(result) >= 2:
                    return match.group(0).strip()
        
        # Fallback: standalone batch code on its own line (for UNIBIC-style labels)
        # Look for lines that contain "/" and ":" (typical UNIBIC batch format like "02-195/L1/P91/13:43")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        batch_pattern = re.compile(r'^([A-Z0-9]+[\-/][A-Z0-9]+[\-/][A-Z0-9/]+[:/]\d{2}:\d{2})$')
        for line in lines:
            if batch_pattern.match(line):
                return line.strip()
        
        # Fallback: batch code after dates on MRP line (HUL-style: "520/- 17/12/25 16/12/26 JK5C2")
        hul_batch = re.search(r"/\s*-\s+\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}/\d{1,2}/\d{2,4}\s+([A-Z0-9]{4,})", text)
        if hul_batch:
            return hul_batch.group(1)
        
        return None

    def _extract_address(self, text: str) -> Optional[str]:
        normalized = re.sub(r'\s*\n\s*', ' ', text)
        patterns = [
            # Priority: Mktd. by address with explicit INDIA ending
            r"Mktd\.?\s*by\s*:\s*[A-Za-z][A-Za-z\s&,\.]+?,\s*([A-Za-z0-9,.\-\s()]+?\d{3}\s?\d{3}\s*\(INDIA\))",
            # Mktd. by address (shorter, until newline or keyword)
            r"Mktd\.?\s*by\s*:\s*[A-Za-z][A-Za-z\s&,\.]+?,\s*([A-Za-z0-9,.\-\s()]+?\d{3}\s?\d{3})",
            # Address with 6-digit PIN code (stop at known keywords)
            r"([A-Za-z0-9,.\-\s]{10,}?\b\d{3}\s?\d{3}\b)",
        ]
        skip_keywords = ['nutritional', 'energy', 'serve', 'serving', 'serves',
                         'per 100g', 'per serve', '%rda', 'nutrients',
                         'protein', 'carbohydrate', 'sugar', 'fat']
        for pattern in patterns:
            for match in re.finditer(pattern, normalized, re.IGNORECASE):
                result = match.group(0).strip()
                lower_result = result.lower()
                if not any(kw in lower_result for kw in skip_keywords):
                    return result
        return None

    def _extract_origin(self, text: str) -> Optional[str]:
        patterns = [
            r"Country\s+of\s+Origin[:\s]+([A-Za-z\s]+?)(?:\n|$)",
            r"PRODUCT\s+OF\s+([A-Za-z\s]+?)(?:\n|$)",
            r"Made\s+in[:\s]+([A-Za-z\s]+?)(?:\n|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_commodity_name(self, text: str) -> Optional[str]:
        normalized = re.sub(r'\s*\n\s*', ' ', text)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        
        patterns = [
            r"(?:Product|Commodity|Item)\s*(?:Name)?\s*[:\s]+([A-Za-z][A-Za-z\s]+?)(?:\s*\n|\s*$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                result = match.group(1).strip()
                if len(result) >= 3:
                    return result
        
        # Fallback: extract from "How to use" line (e.g., "of Milk'O'Mix Arjun-Lemon Herbal Tea Infusion in")
        how_to_use_match = re.search(r"of\s+([A-Za-z][A-Za-z'O\-]+(?:\s+[A-Za-z'O\-]+)+?)(?:\s+in\s|\s+with\s)", normalized, re.IGNORECASE)
        if how_to_use_match:
            result = how_to_use_match.group(1).strip()
            if len(result) >= 5:
                return result
        
        # Skip non-product lines
        skip_words = ['nutritional', 'ingredients', 'manufactured', 'mfd', 'marketed', 
                      'fssai', 'lic', 'keep', 'city', 'clean', 'india', 'of india',
                      'product of', 'vegetarian', 'usp', 'unit sale', 'best before',
                      'use by', 'batch', 'mfg', 'date', 'keep your', 'other',
                      'max.', 'retail', 'price', 'net quantity', 'inclusive', 'taxes',
                      'bikano', 'bikanervala', 'feedback', 'complaints', 'brand',
                      'owned', 'marketed by', 'manufactured by', 'mfd. by',
                      'for feedback', 'write to', 'consumer service', 'contact',
                      'email', 'website', 'www', 'call', 'toll free', 'phone',
                      'address', 'corporate', 'registered', 'office',
                      'storage', 'store in', 'cool', 'dry', 'hygienic',
                      'allergen', 'may contain', 'contains', 'ingredients:',
                      'how to use', 'directions', 'servings', 'serving size',
                      'approx.', 'approx values', 'guideline', 'daily amount',
                      'energy', 'protein', 'fat', 'carbohydrate', 'sodium',
                      'cholesterol', 'trans fat', 'saturated', 'sugar',
                      'vitamin', 'iron', 'calcium', 'fibre', 'fiber',
                      'quantity per', 'per 100g', 'per serve', '% rda',
                      'indulge', 'favourites', 'find more', 'bhujia',
                      'khatta meetha', 'navrattan', 'scan for', 'good mood',
                      'packaged in', 'protective atmosphere', 'keep your city',
                      'for epr', 'barcode', 'also try', 'explore',
                      'since 1956', 'world of', 'wholesome', 'enjoy',
                      'weikfield', 'since', 'since 1953', 'quality & goodness',
                      'made in a', 'registered trademark', 'copyright',
                      'all rights', 'nutrition advice', 'toll free',
                      'for feedback', 'please contact', 'quality assurance',
                      'p.o. box', 'tel. no.', 'mon-sat', 'allergens',
                      'processed in', 'may contain traces', 'store in a cool',
                      'do not buy', 'see bottom', 'unit sale price',
                      'weight control', 'helpful in', 'remove toxins',
                      'full of', 'vit. a', 'buy online', 'net wt.',
                      'no. of serves', 'serving size', 'per serve',
                      'omega', 'mufa', 'pufa', 'added sugar',
                      'from organic', 'no refined', 'sweetened with',
                      'icmr-nin', 'men-moderate', 'recommended daily',
                      'let\'s connect', 'for feedback or complaints',
                      'consumer care cell', 'marketed by address',
                      'us.fda', 'iso 22000',                       'non-gmo', 'peanuts',
                      'proprietary food', 'ingredients:',
                      'proprietary food', 'ingredients:',
                      'nutritional information', 'approx. values',
                      'no. of serves', 'serving size', '2 tbsp',
                      'per 100g', 'per serve', '%rda', 'nutrients',
                      'energy (kcal)', 'protein (g)', 'total carbohydrates',
                      'dietary fiber', 'total sugar', 'added sugar',
                      '(from organic jaggery)', 'total fat', 'saturated fat',
                      'trans fat', 'mufa', 'omega-6', 'cholesterol',
                      'sodium (mg)', 'recommended daily allowance',
                      'icmr-nin 2020', 'men-moderate work', 'no refined sugar',
                      'sweetened with organic jaggery only',
                      'manufactured by:', 'fssai lic. no.',
                      'marketed by:', 'das superfoods', 'das foodtech',
                      'sonasan', 'prantij', 'sabarkantha', 'gujarat',
                      'let\'s connect', 'for feedback or',
                      'complaints, please reach out to',
                      'consumer care cell at the',
                      'marketed by address, call or email us at',
                      'support@pintola.in',
                      'mrp:', 'incl. of all taxes', 'usp:',
                      'batch no.:', 'mfg. date:', 'use by:',
                      'net weight', 'biscuits net weight',
                      'max. retail price', 'incl. of all taxes',
                      'date of mfg.', 'use by:', 'lot no.',
                      'machine code', 'for manufacturing unit',
                      'please scan', 'characters of the batch',
                      'mfd. by:', 'b1-lic.', 'b4-lic.', 'b7-lic.', 'b8-lic.',
                      'mktd. by:', 'for feedback/customer',
                      'write to', 'indicating batch', 'consumer service manager',
                      'at above mentioned', 'marketed by',
                      'email:', 'call at', 'website:', 'www.bikano.com',
                      'net quantity:', 'max. retail price:',
                      'inclusive of all taxes)', 'usp:', 'batch no.:',
                      'date of mfg.:', 'use by:',
                      'nutritional information**', 'serving size:',
                      'servings per package:', 'per 100g', '% rda per serve*',
                      'approx values', 'approximate values',
                      '*per serve percentage', 'recommended dietary allowance',
                      'average adult per day',
                      'product of india', 'other',
                      'keep your city clean', 'for epr details',
                      'scan the barcode', 'mpkg. mfd. by: montage']
        # Also skip lines that are mostly numbers with special chars (like nutritional data)
        numeric_pattern = re.compile(r'^[\d\s\.\,\-\/\%\+\*]+$')
        for line in lines:
            lower = line.lower().strip()
            if len(line) >= 5 and not any(w in lower for w in skip_words):
                # Skip lines that are mostly numbers or codes
                if not re.match(r'^[\d\s\-\.\/:]+$', line) and not numeric_pattern.match(line.strip()):
                    return line
        return None
