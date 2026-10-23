import base64
import io
from PyPDF2 import PdfReader
from app.notices import render_notice_texts, generate_notice_pdf


def test_pdf_generation_facts_and_todo():
    """
    Test 5 (Mandatory):
    PDF generation produces a non-empty PDF containing the case facts and the visible TODO marker.
    """
    case_data = {
        "case_id": "case_test_9999",
        "user_id": "user_victim_101",
        "urls": ["https://infringing-host.net/post/9821.jpg"],
        "evidence_sha256": "4b725f466b046187ee09ab56c1f1ec7c8b0e8b1b22e1b12b55f5f4b5f4a5f4e5",
        "evidence_hashes": [
            "phash_8000000000000000",
            "dhash_0000000000000000"
        ],
        "created_at": "2026-10-23T01:00:00Z"
    }

    # 1. Text notices render
    text_notices = render_notice_texts(case_data)
    assert "TODO: verify legal wording" in text_notices["grievance_notice"]
    assert "case_test_9999" in text_notices["grievance_notice"]
    assert "Rule 3(2)(b)" in text_notices["grievance_notice"]

    # 2. PDF generation
    pdf_b64 = generate_notice_pdf(case_data)
    assert pdf_b64 is not None and len(pdf_b64) > 0

    pdf_bytes = base64.b64decode(pdf_b64)
    assert len(pdf_bytes) > 500, "PDF size must be substantial"

    # Extract text from generated PDF and assert required facts
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() or ""

    assert "TODO: verify legal wording" in full_text
    assert "case_test_9999" in full_text
    assert "user_victim_101" in full_text
    assert "https://infringing-host.net/post/9821.jpg" in full_text
    assert "4b725f466b046187ee09ab56c1f1ec7c8b0e8b1b22e1b12b55f5f4b5f4a5f4e5" in full_text
    assert "Rule 3(2)(b)" in full_text
