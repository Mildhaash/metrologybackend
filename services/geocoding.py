# services/geocoding.py

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_cache = {}
_cache_ttl = 86400


def reverse_geocode(lat: float, lng: float) -> Optional[str]:
    cache_key = f"{round(lat, 4)},{round(lng, 4)}"
    if cache_key in _cache:
        entry = _cache[cache_key]
        if time.time() - entry["ts"] < _cache_ttl:
            return entry["address"]

    try:
        import urllib.request
        import json

        url = (
            f"https://nominatim.openstreetmap.org/reverse?"
            f"lat={lat}&lon={lng}&format=json&zoom=18&addressdetails=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "MetrologyComplianceChecker/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            address = data.get("display_name", "")
            if address:
                _cache[cache_key] = {"address": address, "ts": time.time()}
                return address
    except Exception as e:
        logger.warning(f"Reverse geocoding failed for {lat},{lng}: {e}")

    return None


def get_short_address(lat: float, lng: float) -> Optional[str]:
    full = reverse_geocode(lat, lng)
    if not full:
        return None
    parts = [p.strip() for p in full.split(",")]
    return ", ".join(parts[:3]) if len(parts) > 3 else full
