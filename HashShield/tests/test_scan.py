import pytest
from app.config import settings
from app.discovery import discovery_cache


def test_scan_requires_consent(client, sample_image_bytes):
    response = client.post(
        "/v1/scan",
        files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")},
        data={"consent": "false", "intimate": "false", "is_minor": "false"},
    )
    assert response.status_code == 400
    assert "consent" in response.json()["detail"].lower()


def test_scan_minor_safety_valve(client, sample_image_bytes):
    response = client.post(
        "/v1/scan",
        files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")},
        data={"consent": "true", "intimate": "false", "is_minor": "true"},
    )
    assert response.status_code == 422
    data = response.json()
    assert "1098" in data["detail"]
    assert "cybercrime.gov.in" in data["detail"]


def test_scan_intimate_redirects_to_stopncii(client, sample_image_bytes):
    response = client.post(
        "/v1/scan",
        files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")},
        data={"consent": "true", "intimate": "true", "is_minor": "false"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intimate"] is True
    assert data["stop_ncii"] is not None
    assert "stopncii.org" in data["stop_ncii"]["url"]
    assert len(data["candidates"]) == 0
    # Hashes should still be computed for user evidence
    assert data["phash"] is not None
    assert data["sha256"] is not None


def test_scan_standard_mock_discovery(client, sample_image_bytes):
    response = client.post(
        "/v1/scan",
        files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")},
        data={"consent": "true", "intimate": "false", "is_minor": "false"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intimate"] is False
    assert len(data["candidates"]) > 0
    # Check candidate structure
    top = data["candidates"][0]
    assert "candidate_id" in top
    assert "page_url" in top
    assert "domain" in top
    assert top["match_type"] in ["full", "partial", "similar"]
    assert "distance" in top
    assert top["verified"] in [True, False, None]


def test_scan_daily_limit_exceeded(client, sample_image_bytes, unrelated_image_bytes, monkeypatch):
    monkeypatch.setattr(settings, "DISCOVER_DAILY_LIMIT", 1)
    discovery_cache.clear()
    
    # First call succeeds
    res1 = client.post(
        "/v1/scan",
        files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")},
        data={"consent": "true", "intimate": "false", "is_minor": "false"},
    )
    assert res1.status_code == 200

    # Second call for different image hits daily limit (cache miss triggers check_and_increment_daily_quota)
    res2 = client.post(
        "/v1/scan",
        files={"file": ("test2.jpg", unrelated_image_bytes, "image/jpeg")},
        data={"consent": "true", "intimate": "false", "is_minor": "false"},
    )
    assert res2.status_code == 429
    assert "Daily discovery limit" in res2.json()["detail"]
