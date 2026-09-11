from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
import logging
from db import require_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])


def _format_scan_date(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


@router.get("")
async def list_products(
    status: str = Query(None, description="Filter by compliance status"),
    search: str = Query(None, description="Search by product name"),
    sort_by: str = Query("last_scanned", description="Sort field"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = require_db()
    try:
        pipeline = []

        if search:
            pipeline.append(
                {"$match": {"extracted_fields.commodity_name": {"$regex": search, "$options": "i"}}}
            )

        # Sort before grouping so $first picks the latest scan per product.
        pipeline.append({"$sort": {"scanned_at": -1}})

        pipeline.extend([
            {
                "$group": {
                    "_id": "$extracted_fields.commodity_name",
                    "total_scans": {"$sum": 1},
                    "compliant_count": {
                        "$sum": {"$cond": [{"$eq": ["$overall_status", "compliant"]}, 1, 0]}
                    },
                    "non_compliant_count": {
                        "$sum": {"$cond": [{"$eq": ["$overall_status", "non-compliant"]}, 1, 0]}
                    },
                    "latest_scan": {"$max": "$scanned_at"},
                    "latest_status": {"$first": "$overall_status"},
                    "latest_id": {"$first": {"$toString": "$_id"}},
                    "latest_fields": {"$first": "$extracted_fields"},
                }
            },
        ])

        if status == "compliant":
            pipeline.append({"$match": {"compliant_count": {"$gt": 0}, "non_compliant_count": 0}})
        elif status == "non-compliant":
            pipeline.append({"$match": {"non_compliant_count": {"$gt": 0}}})

        pipeline.append({"$sort": {"latest_scan": -1}})
        pipeline.append({"$skip": offset})
        pipeline.append({"$limit": limit})

        results = list(db.scans.aggregate(pipeline))

        products = []
        for r in results:
            products.append({
                "id": r["_id"] or "Unknown",
                "name": r["_id"] or "Unknown Product",
                "total_scans": r["total_scans"],
                "compliant_count": r["compliant_count"],
                "non_compliant_count": r["non_compliant_count"],
                "latest_status": r["latest_status"],
                "latest_scan": _format_scan_date(r.get("latest_scan")),
                "latest_scan_id": r.get("latest_id"),
                "fields": r.get("latest_fields", {}) or {},
            })

        total = len(products)

        return {"products": products, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("list products failed")
        raise HTTPException(status_code=500, detail=f"Failed to list products: {e}")


@router.get("/{product_name:path}")
async def get_product_detail(product_name: str):
    db = require_db()
    try:
        scans = list(
            db.scans.find({"extracted_fields.commodity_name": product_name})
            .sort("scanned_at", -1)
            .limit(20)
        )

        if not scans:
            raise HTTPException(status_code=404, detail="Product not found")

        total = len(scans)
        compliant = sum(1 for s in scans if s.get("overall_status") == "compliant")

        return {
            "name": product_name,
            "total_scans": total,
            "compliant_count": compliant,
            "non_compliant_count": total - compliant,
            "compliance_rate": round(compliant / total * 100, 1) if total else 0,
            "scans": [
                {
                    "id": str(s["_id"]),
                    "status": s.get("overall_status"),
                    "scanned_at": _format_scan_date(s.get("scanned_at")),
                    "fields": s.get("extracted_fields", {}) or {},
                    "violations": s.get("violations_summary", {}) or {},
                }
                for s in scans
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get product detail failed")
        raise HTTPException(status_code=500, detail=f"Failed to load product: {e}")
