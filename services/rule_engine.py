# services/rule_engine.py

import json
import re
from typing import Dict, List, Any

class RuleEngine:
    def __init__(self):
        with open("rules/rules.json", encoding="utf-8") as f:
            self.rules = json.load(f)
        with open("rules/font_size_table.json", encoding="utf-8") as f:
            self.font_table = json.load(f)
    
    def validate(self, extracted_fields: Dict, font_analysis: Dict = None) -> Dict:
        violations = []
        passed = []
        
        for rule in self.rules:
            result = self._check_rule(rule, extracted_fields, font_analysis)
            if result["status"] == "fail":
                violations.append(result)
            else:
                passed.append(result)
        
        severity_counts = {
            "critical": len([v for v in violations if v["severity"] == "critical"]),
            "major": len([v for v in violations if v["severity"] == "major"]),
            "minor": len([v for v in violations if v["severity"] == "minor"]),
            "needs_review": len([v for v in violations if v["severity"] == "needs_review"]),
        }
        
        pass_rate = len(passed) / len(self.rules) if self.rules else 1
        return {
            "overall_status": "compliant" if pass_rate >= 0.9 else "non-compliant",
            "violations": violations,
            "passed": passed,
            "summary": {
                "total_checks": len(self.rules),
                "passed": len(passed),
                "failed": len(violations),
                **severity_counts
            }
        }
    
    def _check_rule(self, rule: Dict, fields: Dict, fonts: Dict = None) -> Dict:
        field_value = fields.get(rule["field"])
        rule_id = rule["rule_id"]
        severity = rule.get("severity", "medium")
        
        # Presence check
        if rule["validation"]["type"] == "presence":
            if not field_value:
                return self._fail(rule, "Field is missing")
        
        # Regex format check (MRP)
        if rule["validation"]["type"] == "regex":
            pattern = rule["validation"]["pattern"]
            if not re.search(pattern, field_value or "", re.IGNORECASE):
                return self._fail(rule, f"Format non-compliant: {field_value}")
            # Rs / ₹ symbol check (e.g. MRP rule): declaration must contain
            # a currency marker — "Rs", "Rs.", "Re.", "INR", "₹" or "Rupees".
            currency_pattern = rule["validation"].get("currency_pattern")
            if currency_pattern:
                if not re.search(currency_pattern, field_value or "", re.IGNORECASE):
                    currency_msg = rule["validation"].get(
                        "currency_error",
                        "Missing Rs./₹ currency symbol",
                    )
                    return self._fail(
                        rule, f"{currency_msg}: {field_value}"
                    )
        
        # Font size check
        if rule["validation"]["type"] == "font_size" and fonts:
            panel_area = fonts.get("panel_area_cm2", 0)
            min_height = self._get_min_font_height(panel_area)
            
            for font in fonts.get("detected_font_heights", []):
                if font.get("height_mm", 0) < min_height:
                    return self._fail(rule, 
                        f"Font size {font.get('height_mm')}mm below minimum {min_height}mm")
        
        # Language check
        if rule["validation"]["type"] == "language":
            allowed = rule["validation"]["allowed"]
            if field_value and field_value.lower() not in allowed:
                return self._fail(rule, f"Language '{field_value}' not allowed")
        
        # Not contain check (misleading words)
        if rule["validation"]["type"] == "not_contain":
            words = rule["validation"]["words"]
            if field_value:
                for word in words:
                    if word.lower() in field_value.lower():
                        return self._fail(rule, f"Contains prohibited word: '{word}'")

        # --- Added: composite check (e.g. "at least one of phone/email required") ---
        if rule["validation"]["type"] == "composite":
            requires = rule["validation"].get("requires", [])
            at_least_one = rule["validation"].get("at_least_one", False)
            values = [fields.get(f) for f in requires]
            if at_least_one:
                if not any(values):
                    return self._fail(rule, f"None of the required fields are present: {', '.join(requires)}")
            else:
                if not all(values):
                    return self._fail(rule, f"Missing required fields: {', '.join(requires)}")
        
        return self._pass(rule)
    
    def _fail(self, rule: Dict, message: str) -> Dict:
        return {
            "rule_id": rule["rule_id"],
            "rule_section": rule.get("section", ""),
            "field": rule["field"],
            "status": "fail",
            "severity": rule.get("severity", "medium"),
            "message": message,
            "suggestion": rule.get("suggestion", "")
        }
    
    def _pass(self, rule: Dict) -> Dict:
        return {
            "rule_id": rule["rule_id"],
            "rule_section": rule.get("section", ""),
            "field": rule["field"],
            "status": "pass",
            "severity": rule.get("severity", "medium"),
            "message": rule.get("description", "Check passed")
        }
    
    def _get_min_font_height(self, panel_area_cm2: float) -> float:
        # Added: original plan looped without doing anything and always returned 1.0.
        # This now actually checks against Table II in font_size_table.json.
        for row in self.font_table["length_area_number"]["rules"]:
            if panel_area_cm2 <= row["panel_area_cm2_max"]:
                return row["min_normal_mm"]
        return 6.0