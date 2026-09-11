# routes/dashboard.py

from fastapi import APIRouter, HTTPException
import logging
from routes.auth import get_current_user
from db import require_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_stats(current_user=None):
    db = require_db()

    try:
        total_scans = db.scans.count_documents({})
        compliant = db.scans.count_documents({"overall_status": "compliant"})
        non_compliant = db.scans.count_documents({"overall_status": "non-compliant"})

        violations_by_type = list(
            db.violations.aggregate(
                [
                    {"$group": {"_id": "$rule_id", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 10},
                ]
            )
        )

        formatted_violations = [
            {"rule_id": v["_id"], "count": v["count"]} for v in violations_by_type if v.get("_id")
        ]

        severity_agg = list(
            db.violations.aggregate(
                [
                    {"$group": {"_id": "$severity", "count": {"$sum": 1}}},
                ]
            )
        )
        severity_breakdown = {"critical": 0, "major": 0, "minor": 0, "needs_review": 0}
        for s in severity_agg:
            key = s.get("_id", "major")
            if key in severity_breakdown:
                severity_breakdown[key] = s["count"]

        return {
            "total_scans": total_scans,
            "compliant": compliant,
            "non_compliant": non_compliant,
            "violations_by_type": formatted_violations,
            "severity_breakdown": severity_breakdown,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("dashboard stats failed")
        raise HTTPException(status_code=500, detail=f"Failed to load dashboard stats: {e}")


@router.get("/recent")
def get_recent_scans(limit: int = 10, current_user=None):
    db = require_db()

    try:
        scans = list(
            db.scans.find()
            .sort("scanned_at", -1)
            .limit(limit)
        )

        for s in scans:
            s["_id"] = str(s["_id"])
            if s.get("scanned_by"):
                s["scanned_by"] = str(s["scanned_by"])
            # Convert violation ObjectIds to strings for JSON serialization
            if isinstance(s.get("violations"), list):
                s["violations"] = [str(v) for v in s["violations"]]
            # Ensure BSON datetimes don't break JSON serialization
            scanned_at = s.get("scanned_at")
            if scanned_at is not None and not isinstance(scanned_at, str):
                try:
                    s["scanned_at"] = scanned_at.isoformat()
                except Exception:
                    s["scanned_at"] = str(scanned_at)

        return {"scans": scans}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("dashboard recent failed")
        raise HTTPException(status_code=500, detail=f"Failed to load recent scans: {e}")
