from fastapi import APIRouter, Query, HTTPException
import logging
from db import require_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ecommerce", tags=["ecommerce"])

PLATFORMS = [
    {"id": "amazon", "name": "Amazon India", "color": "#FF9900", "base_url": "https://www.amazon.in/s?k="},
    {"id": "flipkart", "name": "Flipkart", "color": "#2874F0", "base_url": "https://www.flipkart.com/search?q="},
    {"id": "bigbasket", "name": "BigBasket", "color": "#89C045", "base_url": "https://www.bigbasket.com/ps/?q="},
    {"id": "jiomart", "name": "JioMart", "color": "#0078AD", "base_url": "https://www.jiomart.com/search/"},
]


@router.get("/compare")
async def compare_products(
    product_name: str = Query(..., description="Product name to search"),
):
    db = require_db()
    try:
        scans = list(
            db.scans.find({"extracted_fields.commodity_name": {"$regex": product_name, "$options": "i"}})
            .sort("scanned_at", -1)
            .limit(5)
        )

        latest = scans[0] if scans else None
        fields = latest.get("extracted_fields", {}) if latest else {}

        listings = []
        for platform in PLATFORMS:
            listings.append({
                "platform": platform["name"],
                "platform_id": platform["id"],
                "color": platform["color"],
                "search_url": f"{platform['base_url']}{product_name.replace(' ', '+')}",
                "compliance_score": 85 if latest else None,
                "price": None,
                "status": "found" if latest else "not_found",
            })

        return {
            "product_name": product_name,
            "reference_fields": fields,
            "total_scans": len(scans),
            "listings": listings,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ecommerce compare failed")
        raise HTTPException(status_code=500, detail=f"Failed to compare products: {e}")


@router.post("/lookup")
async def lookup_product(body: dict):
    db = require_db()
    try:
        product_name = body.get("product_name", "")
        if not product_name:
            raise HTTPException(status_code=400, detail="product_name is required")

        scans = list(
            db.scans.find({"extracted_fields.commodity_name": {"$regex": product_name, "$options": "i"}})
            .sort("scanned_at", -1)
            .limit(10)
        )

        fields = {}
        if scans:
            latest = scans[0]
            fields = latest.get("extracted_fields", {})

        return {
            "query": product_name,
            "found_scans": len(scans),
            "extracted_fields": fields,
            "platforms": [
                {
                    "name": p["name"],
                    "search_url": f"{p['base_url']}{product_name.replace(' ', '+')}",
                    "color": p["color"],
                }
                for p in PLATFORMS
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ecommerce lookup failed")
        raise HTTPException(status_code=500, detail=f"Failed to look up product: {e}")


@router.get("/compliance-score")
async def platform_compliance_scores(
    product_name: str = Query(...),
):
    db = require_db()
    try:
        pipeline = [
            {"$match": {"extracted_fields.commodity_name": {"$regex": product_name, "$options": "i"}}},
            {"$group": {
                "_id": "$overall_status",
                "count": {"$sum": 1},
            }},
        ]
        results = list(db.scans.aggregate(pipeline))

        total = sum(r["count"] for r in results)
        compliant = next((r["count"] for r in results if r["_id"] == "compliant"), 0)

        return {
            "product_name": product_name,
            "total_scans": total,
            "compliance_rate": round(compliant / total * 100, 1) if total else 0,
            "breakdown": {r["_id"]: r["count"] for r in results if r.get("_id")},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ecommerce compliance-score failed")
        raise HTTPException(status_code=500, detail=f"Failed to load compliance score: {e}")
