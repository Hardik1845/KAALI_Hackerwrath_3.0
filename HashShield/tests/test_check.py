import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock
from app.storage import storage
from app.models import CaseCheckResultItem


@pytest.fixture
def existing_case(client):
    case_resp = client.post(
        "/v1/cases",
        json={
            "user_id": "victim_check_user",
            "urls": ["https://fraudster-portal.example/photo.jpg"],
            "evidence_hashes": ["fake_evidence_hash_123"],
            "notes": "Testing check flow",
        },
    )
    assert case_resp.status_code == 200
    return case_resp.json()["case_id"]


def test_check_case_not_found(client):
    res = client.post("/v1/cases/case_nonexistent/check")
    assert res.status_code == 404


@patch("app.checker.check_url_removal", new_callable=AsyncMock)
def test_check_url_removed_404(mock_check, client, existing_case):
    now_iso = datetime.now(timezone.utc).isoformat()
    mock_check.return_value = CaseCheckResultItem(
        url="https://fraudster-portal.example/photo.jpg",
        status_code=404,
        removed_assessment="likely_removed",
        checked_at=now_iso,
        note="HTTP 404 indicates page or asset has been taken down.",
    )

    res = client.post(f"/v1/cases/{existing_case}/check")
    assert res.status_code == 200
    data = res.json()
    assert data["case_id"] == existing_case
    assert "user confirmation is required" in data["advice"]
    assert len(data["results"]) == 1
    assert data["results"][0]["status_code"] == 404
    assert data["results"][0]["removed_assessment"] == "likely_removed"


@patch("app.checker.check_url_removal", new_callable=AsyncMock)
def test_check_url_inconclusive_200(mock_check, client, existing_case):
    now_iso = datetime.now(timezone.utc).isoformat()
    mock_check.return_value = CaseCheckResultItem(
        url="https://fraudster-portal.example/photo.jpg",
        status_code=200,
        removed_assessment="inconclusive",
        checked_at=now_iso,
        note="HTTP 200 OK received; content may still be live.",
    )

    res = client.post(f"/v1/cases/{existing_case}/check")
    assert res.status_code == 200
    data = res.json()
    assert data["results"][0]["removed_assessment"] == "inconclusive"
    assert data["results"][0]["status_code"] == 200


def test_jobs_due_reporting(client, existing_case):
    # Initially not sent, so no due jobs
    res0 = client.get("/v1/jobs/due")
    assert res0.status_code == 200
    assert len(res0.json()["jobs"]) == 0

    # Mark sent
    client.post(f"/v1/cases/{existing_case}/sent")

    # Manually backdate due_at in storage to simulate elapsed 24-hour SLA
    past_due = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    storage.cases[existing_case]["due_at"] = past_due
    storage.cases[existing_case]["deadline"] = past_due

    # Now jobs/due should list it as overdue
    res1 = client.get("/v1/jobs/due")
    assert res1.status_code == 200
    jobs = res1.json()["jobs"]
    assert len(jobs) >= 1
    assert any(j["case_id"] == existing_case for j in jobs)
