from datetime import datetime, timezone
from app.config import settings


def test_case_lifecycle_and_sla_timer(client):
    """
    Test 6 (Mandatory):
    Complete case lifecycle:
    1. Case creation
    2. /sent sets deadline (SLA_HOURS, default 24)
    3. /cases/{id} shows countdown seconds remaining
    4. /resolve closes or escalates to cybercrime.gov.in / 1930
    """
    # 1. Create Case
    create_res = client.post("/v1/cases", json={
        "user_id": "ananya_s",
        "urls": ["https://anon-leak-hub.cz/post/v88291"],
        "evidence_hashes": ["phash_8000000000000000"],
        "notes": "Suspected leaked photo from compromised account"
    })
    assert create_res.status_code == 200
    case_id = create_res.json()["case_id"]
    assert create_res.json()["status"] == "created"

    # 2. Mark Sent -> sets SLA deadline
    sent_res = client.post(f"/v1/cases/{case_id}/sent")
    assert sent_res.status_code == 200
    sent_data = sent_res.json()
    assert sent_data["status"] == "sent"
    assert sent_data["sla_hours"] == settings.SLA_HOURS
    assert "deadline" in sent_data

    # 3. Get Case -> shows seconds remaining
    detail_res = client.get(f"/v1/cases/{case_id}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["status"] == "sent"
    assert detail_data["seconds_remaining"] is not None
    assert 0 < detail_data["seconds_remaining"] <= (settings.SLA_HOURS * 3600)

    # 4. Resolve: Not Removed -> Escalation
    resolve_unremoved = client.post(f"/v1/cases/{case_id}/resolve", json={"removed": False})
    assert resolve_unremoved.status_code == 200
    esc_data = resolve_unremoved.json()
    assert esc_data["status"] == "escalated"
    assert esc_data["escalation"]["portal"] == "https://cybercrime.gov.in"
    assert esc_data["escalation"]["helpline"] == "1930"
    assert "stop_ncii" in esc_data["escalation"]

    # 5. Resolve: Removed -> Closed
    resolve_removed = client.post(f"/v1/cases/{case_id}/resolve", json={"removed": True})
    assert resolve_removed.status_code == 200
    closed_data = resolve_removed.json()
    assert closed_data["status"] == "closed"
    assert closed_data["escalation"] is None
