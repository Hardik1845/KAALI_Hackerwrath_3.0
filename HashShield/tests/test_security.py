import io
import os
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.storage import storage


def test_upload_rejection_invalid_magic_bytes(client):
    """
    Test 7a (Mandatory):
    Upload rejection when file format has invalid magic bytes or spoofed extension.
    """
    # 1. Plain text with spoofed .jpg extension
    spoofed_bytes = b"Hello, this is just plain text masquerading as a JPEG image!"
    res = client.post(
        "/v1/hash",
        files={"file": ("fake_image.jpg", spoofed_bytes, "image/jpeg")}
    )
    assert res.status_code == 400
    assert "Invalid image file format" in res.json()["detail"]

    # 2. Binary trash
    trash_bytes = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c"
    res_trash = client.post(
        "/v1/hash",
        files={"file": ("corrupt.png", trash_bytes, "image/png")}
    )
    assert res_trash.status_code == 400


def test_upload_rejection_oversize(client):
    """
    Test 7b (Mandatory):
    Rejection when upload exceeds maximum allowed size (10 MB).
    """
    # Generate 11 MB of zero bytes
    oversize_bytes = b"\xff\xd8\xff" + (b"\x00" * (11 * 1024 * 1024))
    res = client.post(
        "/v1/hash",
        files={"file": ("huge.jpg", oversize_bytes, "image/jpeg")}
    )
    assert res.status_code == 400
    assert "exceeds maximum allowed size" in res.json()["detail"]


def test_minor_protection_policy(client):
    """
    Mandatory Rule:
    If anything in the request involves a person under 18, the service must not process it
    and must return a clear message pointing to specialized help (cybercrime.gov.in, Childline 1098).
    """
    # Explicit flag
    res_flag = client.post("/v1/cases", json={
        "user_id": "test_user",
        "urls": ["https://site.com/image.jpg"],
        "evidence_hashes": ["phash_8000000000000000"],
        "is_minor": True
    })
    assert res_flag.status_code == 422
    assert "1098" in res_flag.json()["detail"]
    assert "cybercrime.gov.in" in res_flag.json()["detail"]

    # Keyword in notes
    res_keyword = client.post("/v1/cases", json={
        "user_id": "test_user",
        "urls": ["https://site.com/image.jpg"],
        "evidence_hashes": ["phash_8000000000000000"],
        "notes": "Victim was 16 years old when photo was taken",
        "is_minor": False
    })
    assert res_keyword.status_code == 422
    assert "1098" in res_keyword.json()["detail"]


def test_no_image_bytes_persisted(client, sample_image_bytes):
    """
    Test 8 (Mandatory):
    After running hash and vault operations, assert nothing image-like exists in storage or on disk.
    """
    # Run hash
    res = client.post(
        "/v1/hash",
        files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")}
    )
    assert res.status_code == 200
    hashes = res.json()

    # Register in vault
    client.post("/v1/vault", json={
        "user_id": "ephemeral_user",
        "phash": hashes["phash"],
        "dhash": hashes["dhash"],
        "sha256": hashes["sha256"],
        "label": "Transient Check"
    })

    # Assert storage items contain only hash strings, no binary image data
    vault_items = storage.vault.get("ephemeral_user", [])
    assert len(vault_items) == 1
    item = vault_items[0]

    # Verify attributes are strictly text/metadata
    assert isinstance(item.phash, str)
    assert isinstance(item.sha256, str)
    assert len(item.phash) == 16
    assert len(item.sha256) == 64
    assert not hasattr(item, "image_bytes")
    assert not hasattr(item, "data")

    # Assert no image files were dumped to app directory
    app_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app")
    for root, _, files in os.walk(app_dir):
        for f in files:
            assert not f.endswith((".jpg", ".jpeg", ".png", ".webp")), f"Unwanted image file persisted in app: {f}"


def test_api_key_authentication():
    """
    Test service-to-service auth via X-API-Key.
    """
    unauthed_client = TestClient(app)
    res = unauthed_client.post("/v1/cases", json={
        "user_id": "user_x",
        "urls": ["https://site.com"],
        "evidence_hashes": ["hash"]
    })
    assert res.status_code == 401
