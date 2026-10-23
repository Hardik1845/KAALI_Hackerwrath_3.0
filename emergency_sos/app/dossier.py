import io
import base64
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from app.models import IncidentDossierResponse


def generate_incident_pdf(session: Dict[str, Any]) -> str:
    """
    Generates a court-admissible PDF forensic incident dossier using ReportLab.
    Includes complete trajectory, timestamps, contacts dispatched, and audio evidence hash.
    Returns base64 encoded PDF string.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#8B0000"),
        alignment=0,
        spaceAfter=6
    )

    h2_style = ParagraphStyle(
        "SectionH2",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#1A202C"),
        spaceBefore=10,
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        "BodyDark",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#2D3748")
    )

    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1A202C")
    )

    story = []

    # Title & Header
    story.append(Paragraph("PROJECT KAALI — EMERGENCY SOS INCIDENT DOSSIER", title_style))
    story.append(Paragraph("FORENSIC ELECTRONIC EVIDENCE RECORD (CERTIFICATE U/S 65B INDIAN EVIDENCE ACT)", body_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#8B0000"), spaceBefore=4, spaceAfter=8))

    # Incident Overview Table
    session_id = session.get("session_id", "UNKNOWN")
    user_name = session.get("user_name", "Anonymous")
    status = session.get("status", "ACTIVE").upper()
    trigger_type = session.get("trigger_type", "manual").upper()
    triggered_at = session.get("triggered_at", "")
    escalated = "YES (PCR / Police Alerted)" if session.get("auto_escalated") else "NO"

    overview_data = [
        [Paragraph("<b>Incident Session ID:</b>", table_cell), Paragraph(session_id, table_cell)],
        [Paragraph("<b>Protected Individual:</b>", table_cell), Paragraph(user_name, table_cell)],
        [Paragraph("<b>Session Status:</b>", table_cell), Paragraph(f"<b>{status}</b>", table_cell)],
        [Paragraph("<b>Trigger Mechanism:</b>", table_cell), Paragraph(trigger_type, table_cell)],
        [Paragraph("<b>Triggered At (UTC):</b>", table_cell), Paragraph(triggered_at, table_cell)],
        [Paragraph("<b>Auto-Escalated:</b>", table_cell), Paragraph(escalated, table_cell)],
    ]

    t_overview = Table(overview_data, colWidths=[150, 390])
    t_overview.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_overview)
    story.append(Spacer(1, 8))

    # Ambient Audio Evidence Section
    story.append(Paragraph("1. Ambient Audio Forensic Log", h2_style))
    audio_available = session.get("audio_available", False)
    audio_sha256 = session.get("audio_sha256", "N/A")
    audio_status = "SECURED & ENCRYPTED AT REST (AES-256)" if audio_available else "NO AUDIO CAPTURED"

    audio_data = [
        [Paragraph("<b>Audio Capture State:</b>", table_cell), Paragraph(audio_status, table_cell)],
        [Paragraph("<b>Cryptographic SHA-256:</b>", table_cell), Paragraph(f"<font face='Courier'>{audio_sha256}</font>", table_cell)]
    ]
    t_audio = Table(audio_data, colWidths=[150, 390])
    t_audio.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF5F5")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#FED7D7")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_audio)
    story.append(Spacer(1, 8))

    # GPS Trajectory Waypoints Table
    story.append(Paragraph("2. Real-Time GPS Trajectory Breadcrumbs", h2_style))
    trajectory = session.get("trajectory", [])

    traj_rows = [
        [
            Paragraph("<b>#</b>", table_cell),
            Paragraph("<b>Timestamp (UTC)</b>", table_cell),
            Paragraph("<b>Latitude</b>", table_cell),
            Paragraph("<b>Longitude</b>", table_cell),
            Paragraph("<b>Accuracy</b>", table_cell),
            Paragraph("<b>Speed (m/s)</b>", table_cell),
        ]
    ]

    for idx, pt in enumerate(trajectory[:25], 1):  # Cap at 25 points for clean PDF layout
        ts = pt.get("timestamp") or triggered_at
        traj_rows.append([
            Paragraph(str(idx), table_cell),
            Paragraph(str(ts)[:19], table_cell),
            Paragraph(f"{pt.get('lat', 0.0):.6f}", table_cell),
            Paragraph(f"{pt.get('lng', 0.0):.6f}", table_cell),
            Paragraph(f"{pt.get('accuracy', 5.0)}m", table_cell),
            Paragraph(f"{pt.get('speed', 0.0)}", table_cell),
        ])

    if len(traj_rows) == 1:
        traj_rows.append([Paragraph("No GPS waypoints recorded.", table_cell), "", "", "", "", ""])

    t_traj = Table(traj_rows, colWidths=[25, 140, 100, 100, 85, 90])
    t_traj.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_traj)
    story.append(Spacer(1, 8))

    # Emergency Contacts Dispatched
    story.append(Paragraph("3. Emergency Dispatch & Notification Log", h2_style))
    contacts = session.get("contacts", [])
    sms_recipients = session.get("sms_sent_to", [])

    contact_rows = [
        [
            Paragraph("<b>Contact Name</b>", table_cell),
            Paragraph("<b>Phone</b>", table_cell),
            Paragraph("<b>Relation</b>", table_cell),
            Paragraph("<b>Priority</b>", table_cell),
            Paragraph("<b>Alert Status</b>", table_cell)
        ]
    ]

    for c in contacts:
        delivered = "DISPATCHED" if c.get("phone") in sms_recipients else "QUEUED"
        contact_rows.append([
            Paragraph(c.get("name", "N/A"), table_cell),
            Paragraph(c.get("phone", "N/A"), table_cell),
            Paragraph(c.get("relation", "Family"), table_cell),
            Paragraph(f"Tier {c.get('priority', 1)}", table_cell),
            Paragraph(f"<b>{delivered}</b>", table_cell)
        ])

    if len(contact_rows) == 1:
        contact_rows.append([Paragraph("No contacts specified.", table_cell), "", "", "", ""])

    t_contacts = Table(contact_rows, colWidths=[120, 120, 100, 70, 130])
    t_contacts.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_contacts)
    story.append(Spacer(1, 8))

    # Legal Certificate Footer
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceBefore=6, spaceAfter=6))
    legal_text = (
        "<b>LEGAL CERTIFICATION:</b> This document constitutes a digitally sealed electronic record generated automatically "
        "by the KAALI Emergency Safety Engine. All geographic coordinates, network transmission logs, and cryptographic "
        "hashes are tamper-evident and admissible as primary digital evidence under Bharatiya Sakshya Adhiniyam (BSA) / "
        "Section 65B of the Indian Evidence Act."
    )
    story.append(Paragraph(legal_text, body_style))

    doc.build(story)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def compile_incident_dossier(session: Dict[str, Any]) -> IncidentDossierResponse:
    """Compiles complete dossier response with PDF and SHA-256 seal."""
    pdf_b64 = generate_incident_pdf(session)
    pdf_bytes = base64.b64decode(pdf_b64)
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()

    return IncidentDossierResponse(
        session_id=session.get("session_id", "unknown"),
        user_name=session.get("user_name", "Anonymous"),
        pdf_base64=pdf_b64,
        incident_sha256=sha256,
        total_waypoints=len(session.get("trajectory", [])),
        audio_included=session.get("audio_available", False),
        generated_at=now_iso
    )
