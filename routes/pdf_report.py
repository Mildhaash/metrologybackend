# routes/pdf_report.py

import io
from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

from db import require_db
from routes.auth import get_current_user

router = APIRouter(prefix="/api/scan", tags=["pdf-report"])

SEVERITY_COLORS = {
    "critical": colors.HexColor("#DC2626"),
    "major": colors.HexColor("#EA580C"),
    "minor": colors.HexColor("#CA8A04"),
    "needs_review": colors.HexColor("#9333EA"),
}

STATUS_COLORS = {
    "compliant": colors.HexColor("#16A34A"),
    "non-compliant": colors.HexColor("#DC2626"),
}


def _build_pdf(scan, violations):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=18, spaceAfter=6)
    heading_style = ParagraphStyle("Heading", parent=styles["Heading2"], fontSize=13, spaceAfter=4, spaceBefore=12)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14)
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, leading=11, textColor=colors.grey)

    elements.append(Paragraph("Legal Metrology Compliance Report", title_style))
    elements.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}", small_style))
    elements.append(Spacer(1, 4 * mm))

    overall = scan.get("overall_status", "unknown")
    status_color = STATUS_COLORS.get(overall, colors.grey)
    elements.append(Paragraph(
        f'<font color="{status_color.hexval()}">Overall Status: <b>{overall.upper()}</b></font>',
        body_style
    ))
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph("Product Information", heading_style))
    fields = scan.get("extracted_fields", {})
    product_data = [
        ["Field", "Value"],
        ["Product Name", fields.get("commodity_name", "—")],
        ["Manufacturer", fields.get("manufacturer_name", "—")],
        ["Address", fields.get("manufacturer_address", "—")],
        ["MRP", fields.get("mrp", "—")],
        ["Net Quantity", fields.get("net_quantity", "—")],
        ["Manufacture Date", fields.get("manufacture_date", "—")],
        ["Best Before", fields.get("best_before", "—")],
        ["Consumer Care Phone", fields.get("consumer_care_phone", "—")],
        ["Consumer Care Email", fields.get("consumer_care_email", "—")],
        ["Country of Origin", fields.get("country_of_origin", "—")],
        ["Language", fields.get("language", "—")],
    ]
    t = Table(product_data, colWidths=[55 * mm, 115 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 13),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 4 * mm))

    summary = scan.get("violations_summary", {})
    if summary:
        elements.append(Paragraph("Violations Summary", heading_style))
        sum_data = [
            ["Critical", "Major", "Minor", "Needs Review", "Total"],
            [
                str(summary.get("critical", 0)),
                str(summary.get("major", 0)),
                str(summary.get("minor", 0)),
                str(summary.get("needs_review", 0)),
                str(summary.get("total", 0)),
            ],
        ]
        st = Table(sum_data, colWidths=[34 * mm] * 5)
        st.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(st)
        elements.append(Spacer(1, 4 * mm))

    if violations:
        elements.append(Paragraph("Violation Details", heading_style))
        v_data = [["Rule", "Field", "Severity", "Message"]]
        for v in violations:
            sev = v.get("severity", "")
            sev_color = SEVERITY_COLORS.get(sev, colors.black)
            v_data.append([
                v.get("rule_id", ""),
                v.get("field", ""),
                Paragraph(f'<font color="{sev_color.hexval()}">{sev}</font>', body_style),
                Paragraph(v.get("message", ""), body_style),
            ])
        vt = Table(v_data, colWidths=[35 * mm, 30 * mm, 22 * mm, 83 * mm])
        vt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEADING", (0, 0), (-1, -1), 11),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(vt)
    else:
        elements.append(Paragraph("No violations found — product is compliant.", body_style))

    elements.append(Spacer(1, 6 * mm))
    elements.append(HRFlowable(width="100%", color=colors.HexColor("#D1D5DB")))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        "This report was generated by the Legal Metrology Compliance Checker. "
        "For official use only.",
        small_style
    ))

    doc.build(elements)
    buf.seek(0)
    return buf


@router.get("/{scan_id}/report/pdf")
def generate_pdf_report(scan_id: str, current_user=Depends(get_current_user)):
    db = require_db()
    scan = db.scans.find_one({"_id": ObjectId(scan_id)})
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    violation_ids = scan.get("violations", [])
    violations = []
    if isinstance(violation_ids, list) and violation_ids:
        violations = list(db.violations.find({"_id": {"$in": violation_ids}}))

    pdf_buf = _build_pdf(scan, violations)

    return StreamingResponse(
        pdf_buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="compliance-report-{scan_id}.pdf"'
        },
    )
