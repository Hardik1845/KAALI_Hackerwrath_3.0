import os
import io
import base64
from datetime import datetime, timezone
from typing import Dict, Any, List
from jinja2 import Environment, FileSystemLoader
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from app.config import settings

# Setup Jinja2 templates directory
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True
)


def render_notice_texts(case_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Renders all statutory plain-text notice templates.
    """
    urls = case_data.get("urls", [])
    first_url = urls[0] if urls else "unknown-domain.com"
    domain = case_data.get("domain") or (urls[0].split("/")[2] if "://" in first_url else first_url)

    context = {
        "case_id": case_data.get("case_id", "CASE-UNKNOWN"),
        "date_str": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "domain": domain,
        "urls": urls,
        "evidence_sha256": case_data.get("evidence_sha256") or (case_data.get("evidence_hashes", [""])[0] if case_data.get("evidence_hashes") else "0x0"),
        "evidence_hashes": case_data.get("evidence_hashes", []),
        "sla_hours": settings.SLA_HOURS,
        "host": case_data.get("host", "Network Hosting Provider"),
        "registrar": case_data.get("registrar", "Domain Registrar")
    }

    grievance_tpl = jinja_env.get_template("grievance_notice.txt")
    host_abuse_tpl = jinja_env.get_template("host_abuse_notice.txt")
    search_delist_tpl = jinja_env.get_template("search_delist_notice.txt")

    return {
        "grievance_notice": grievance_tpl.render(context),
        "host_abuse_notice": host_abuse_tpl.render(context),
        "search_delist_notice": search_delist_tpl.render(context)
    }


def generate_notice_pdf(case_data: Dict[str, Any]) -> str:
    """
    Generates a formal, court-admissible forensic evidence dossier & takedown notice as PDF.
    Returns base64 encoded string.
    Contains case facts and the visible marker: 'TODO: verify legal wording'.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#0f172a'),
        alignment=1
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#2563eb'),
        alignment=1
    )

    todo_style = ParagraphStyle(
        'TodoWarning',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#b91c1c'),
        backColor=colors.HexColor('#fef2f2'),
        borderColor=colors.HexColor('#f87171'),
        borderWidth=1,
        borderPadding=6,
        alignment=0,
        spaceAfter=12
    )

    body_style = ParagraphStyle(
        'DocBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#1e293b')
    )

    bold_label = ParagraphStyle(
        'BoldLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#0f172a')
    )

    code_style = ParagraphStyle(
        'CodeStyle',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#0f172a')
    )

    elements = []

    # Title & Subtitle
    elements.append(Paragraph("PROJECT KAALI // HASH SHIELD", title_style))
    elements.append(Paragraph("STATUTORY CEASE & DESIST EVIDENCE DOSSIER", subtitle_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0f172a"), spaceAfter=12))

    # Mandatory Legal Verification Marker
    elements.append(Paragraph(
        "<b>[TODO: verify legal wording]</b> — NOTICE: This automated draft references Section 79 & Rule 3(2)(b) "
        "of the IT Rules, 2021 (Intermediary Guidelines) and IPC/BNS provisions. Review with qualified legal counsel "
        "before official dispatch.",
        todo_style
    ))

    # Metadata Summary Table
    case_id = case_data.get("case_id", "N/A")
    user_id = case_data.get("user_id", "N/A")
    created_at = case_data.get("created_at", datetime.now(timezone.utc).isoformat())

    meta_table_data = [
        [Paragraph("Case Reference ID:", bold_label), Paragraph(case_id, code_style)],
        [Paragraph("Protected Victim ID:", bold_label), Paragraph(user_id, code_style)],
        [Paragraph("Timestamp (UTC):", bold_label), Paragraph(created_at, body_style)],
        [Paragraph("Statutory Remediation SLA:", bold_label), Paragraph(f"{settings.SLA_HOURS} Hours (Mandatory 24h Removal)", body_style)]
    ]
    meta_table = Table(meta_table_data, colWidths=[160, 360])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 12))

    # Section 1: Infringing URLs
    elements.append(Paragraph("<b>1. TARGET INFRINGING LOCATIONS:</b>", bold_label))
    elements.append(Spacer(1, 4))
    urls = case_data.get("urls", [])
    if urls:
        for u in urls:
            elements.append(Paragraph(f"• {u}", code_style))
    else:
        elements.append(Paragraph("None specified", body_style))
    elements.append(Spacer(1, 10))

    # Section 2: Cryptographic Evidence Hashes
    elements.append(Paragraph("<b>2. FORENSIC EVIDENCE CHECKSUMS (ZERO-KNOWLEDGE VERIFIED):</b>", bold_label))
    elements.append(Spacer(1, 4))
    sha256_val = case_data.get("evidence_sha256")
    if sha256_val:
        elements.append(Paragraph(f"• SHA-256 Digest: {sha256_val}", code_style))
    hashes = case_data.get("evidence_hashes", [])
    if hashes:
        for h in hashes:
            elements.append(Paragraph(f"• Hash: {h}", code_style))
    elif not sha256_val:
        elements.append(Paragraph("None registered", body_style))
    elements.append(Spacer(1, 10))

    # Section 3: Host & Network Intelligence (from RDAP)
    lookups = case_data.get("lookups", [])
    if lookups:
        elements.append(Paragraph("<b>3. HOSTING & REGISTRAR INTELLIGENCE (RDAP):</b>", bold_label))
        elements.append(Spacer(1, 4))
        for lk in lookups:
            dom = lk.get("domain", "")
            reg = lk.get("registrar") or "Not Identified"
            hst = lk.get("host") or "Not Identified"
            emails = ", ".join(lk.get("abuse_emails", [])) or "None discovered"
            elements.append(Paragraph(f"<b>Domain:</b> {dom} | <b>Host:</b> {hst} | <b>Registrar:</b> {reg}", body_style))
            elements.append(Paragraph(f"<b>Abuse Contacts:</b> {emails}", code_style))
            elements.append(Spacer(1, 4))
        elements.append(Spacer(1, 6))

    # Section 4: Statutory Legal Directives
    elements.append(Paragraph("<b>4. STATUTORY NOTICE & DEMAND:</b>", bold_label))
    notice_text = (
        f"Under Rule 3(2)(b) of the Information Technology (Intermediary Guidelines and Digital Media Ethics Code) "
        f"Rules, 2021, an intermediary must within {settings.SLA_HOURS} hours take all reasonable and practicable "
        f"measures to remove or disable access to content that exposes the private areas of such individual or shows "
        f"such individual in full or partial nudity or shows or depicts such individual in any sexual act or conduct, "
        f"or is in the nature of impersonation in an electronic form, including artificially morphed images. "
        f"Failure to comply revokes statutory intermediary safe harbor protection under Section 79(1) of the IT Act, 2000."
    )
    elements.append(Paragraph(notice_text, body_style))
    elements.append(Spacer(1, 14))

    # Footer note
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#94a3b8"), spaceAfter=8))
    elements.append(Paragraph(
        "Cryptographically generated by Project KAALI HashShield Engine. No raw image bytes were stored on disk. "
        "Escalations: National Cyber Crime Reporting Portal (cybercrime.gov.in) | Helpline 1930.",
        ParagraphStyle('Footer', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor('#64748b'))
    ))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return base64.b64encode(pdf_bytes).decode("utf-8")
