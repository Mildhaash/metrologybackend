from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import csv
import io
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Shared helper lives in db.py so every route returns the same 503 JSON
# when MONGODB_URI is missing instead of crashing with RuntimeError.
from db import require_db


def _parse_scan_date(value):
    """Return a datetime or None, tolerating datetime / ISO string / missing."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # Handle trailing Z
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None
    return None


def _format_violations_summary(violations_summary) -> str:
    """Render violations_summary whether it is a dict, list, or None."""
    if not violations_summary:
        return ""
    if isinstance(violations_summary, dict):
        # Stored shape: {"total": 2, "high": 1, ...}
        return "; ".join(f"{k}: {v}" for k, v in violations_summary.items())
    if isinstance(violations_summary, list):
        parts = []
        for v in violations_summary:
            if isinstance(v, dict):
                parts.append(v.get("rule_id") or v.get("message") or str(v))
            else:
                parts.append(str(v))
        return "; ".join(parts)
    return str(violations_summary)


@router.get("/summary")
async def report_summary(
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
):
    db = require_db()
    since = datetime.utcnow() - timedelta(days=days)

    try:
        total = db.scans.count_documents({"scanned_at": {"$gte": since}})
        compliant = db.scans.count_documents(
            {"scanned_at": {"$gte": since}, "overall_status": "compliant"}
        )
        non_compliant = db.scans.count_documents(
            {"scanned_at": {"$gte": since}, "overall_status": "non-compliant"}
        )

        # Violations live in the separate `violations` collection (see
        # routes/scan.py), NOT in scans.violations_summary (which is a dict
        # like {"total":..,"high":..}). Query by scan_ids in the period so the
        # date filter matches scans.scanned_at.
        scan_ids = [
            s["_id"]
            for s in db.scans.find(
                {"scanned_at": {"$gte": since}}, {"_id": 1}
            )
        ]
        top_violations: list = []
        if scan_ids:
            pipeline = [
                {"$match": {"scan_id": {"$in": scan_ids}}},
                {"$group": {"_id": "$rule_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10},
            ]
            try:
                top_violations = list(db.violations.aggregate(pipeline))
            except Exception as agg_err:
                # Fall back to created_at filter if scan_id types mismatch
                logger.warning(f"summary violations aggregate failed: {agg_err}")
                top_violations = []

        return {
            "period_days": days,
            "total_scans": total,
            "compliant": compliant,
            "non_compliant": non_compliant,
            "compliance_rate": round(compliant / total * 100, 1) if total else 0,
            "top_violations": [
                {"rule_id": v["_id"], "count": v["count"]}
                for v in top_violations
                if v.get("_id")
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("report summary failed")
        raise HTTPException(status_code=500, detail=f"Failed to build report summary: {e}")


@router.get("/violations")
async def violation_breakdown(
    days: int = Query(30, ge=1, le=365),
):
    db = require_db()
    since = datetime.utcnow() - timedelta(days=days)

    try:
        # Map scan_id -> commodity name for the period
        scan_product: dict = {}
        scan_ids = []
        for s in db.scans.find(
            {"scanned_at": {"$gte": since}},
            {"_id": 1, "extracted_fields.commodity_name": 1},
        ):
            scan_ids.append(s["_id"])
            fields = s.get("extracted_fields") or {}
            scan_product[str(s["_id"])] = fields.get("commodity_name") or "Unknown"

        if not scan_ids:
            return {"violations": []}

        counts: Counter = Counter()
        products_by_rule: dict = defaultdict(set)
        try:
            cursor = db.violations.find(
                {"scan_id": {"$in": scan_ids}},
                {"rule_id": 1, "scan_id": 1},
            )
            violation_docs = list(cursor)
        except Exception as agg_err:
            logger.warning(f"violations fetch failed: {agg_err}")
            violation_docs = []

        for v in violation_docs:
            rule_id = v.get("rule_id") or "unknown"
            counts[rule_id] += 1
            prod = scan_product.get(str(v.get("scan_id")), "Unknown")
            products_by_rule[rule_id].add(prod)

        violations = [
            {
                "rule_id": rule_id,
                "count": count,
                "affected_products": len(products_by_rule[rule_id]),
                "products": sorted(products_by_rule[rule_id])[:5],
            }
            for rule_id, count in counts.most_common()
        ]

        return {"violations": violations}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("violation breakdown failed")
        raise HTTPException(status_code=500, detail=f"Failed to build violation breakdown: {e}")


@router.get("/trends")
async def compliance_trends(
    days: int = Query(30, ge=1, le=365),
):
    db = require_db()
    since = datetime.utcnow() - timedelta(days=days)

    try:
        # Group in Python so string/missing scanned_at values can't crash
        # a $dateToString aggregation stage.
        buckets: dict = defaultdict(lambda: {"total": 0, "compliant": 0, "non_compliant": 0})
        for s in db.scans.find(
            {"scanned_at": {"$gte": since}},
            {"scanned_at": 1, "overall_status": 1},
        ):
            dt = _parse_scan_date(s.get("scanned_at"))
            if dt is None:
                continue
            key = dt.date().isoformat()
            buckets[key]["total"] += 1
            if s.get("overall_status") == "compliant":
                buckets[key]["compliant"] += 1
            elif s.get("overall_status") == "non-compliant":
                buckets[key]["non_compliant"] += 1

        trends = [
            {
                "date": day,
                "total": b["total"],
                "compliant": b["compliant"],
                "non_compliant": b["non_compliant"],
                "compliance_rate": round(b["compliant"] / b["total"] * 100, 1) if b["total"] else 0,
            }
            for day, b in sorted(buckets.items())
        ]

        return {"trends": trends}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("compliance trends failed")
        raise HTTPException(status_code=500, detail=f"Failed to build compliance trends: {e}")


@router.get("/export")
async def export_report(
    days: int = Query(30, ge=1, le=365),
    format: str = Query("csv", description="Export format: csv, pdf, xlsx"),
):
    db = require_db()
    since = datetime.utcnow() - timedelta(days=days)
    try:
        scans = list(db.scans.find({"scanned_at": {"$gte": since}}).sort("scanned_at", -1))

        rows = []
        for scan in scans:
            fields = scan.get("extracted_fields") or {}
            if not isinstance(fields, dict):
                fields = {}
            scanned_at = scan.get("scanned_at")
            if isinstance(scanned_at, datetime):
                scanned_at_str = scanned_at.isoformat()
            elif scanned_at:
                scanned_at_str = str(scanned_at)
            else:
                scanned_at_str = ""
            rows.append({
                "scan_id": str(scan.get("_id", "")),
                "product_name": fields.get("commodity_name", "") or "",
                "status": scan.get("overall_status", "") or "",
                "mrp": fields.get("mrp", "") or "",
                "net_quantity": fields.get("net_quantity", "") or "",
                "manufacturer": fields.get("manufacturer_name", "") or "",
                "best_before": fields.get("best_before", "") or "",
                "scan_date": scanned_at_str,
                "violations": _format_violations_summary(scan.get("violations_summary", "")),
            })

        headers = ["Scan ID", "Product Name", "Status", "MRP", "Net Quantity",
                    "Manufacturer", "Best Before", "Scan Date", "Violations"]

        if format == "xlsx":
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Compliance Report"
            ws.append(headers)
            for r in rows:
                ws.append([r["scan_id"], r["product_name"], r["status"], r["mrp"],
                           r["net_quantity"], r["manufacturer"], r["best_before"],
                           r["scan_date"], r["violations"]])
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename=report_{days}d.xlsx"},
            )

        if format == "pdf":
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib import colors
            from reportlab.lib.units import mm

            buf = io.BytesIO()
            doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm)
            styles = getSampleStyleSheet()
            elements = []
            elements.append(Paragraph(f"Compliance Report — Last {days} Days", styles["Title"]))
            elements.append(Spacer(1, 4 * mm))
            table_data = [headers]
            for r in rows:
                table_data.append([r["scan_id"][:12], r["product_name"][:25], r["status"],
                                   r["mrp"], r["net_quantity"], r["manufacturer"][:25],
                                   r["best_before"], r["scan_date"][:10], r["violations"][:20]])
            t = Table(table_data, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            elements.append(t)
            doc.build(elements)
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=report_{days}d.pdf"},
            )

        # Default: CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        for r in rows:
            writer.writerow([r["scan_id"], r["product_name"], r["status"], r["mrp"],
                             r["net_quantity"], r["manufacturer"], r["best_before"],
                             r["scan_date"], r["violations"]])
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=report_{days}d.csv"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("report export failed")
        raise HTTPException(status_code=500, detail=f"Failed to export report: {e}")
