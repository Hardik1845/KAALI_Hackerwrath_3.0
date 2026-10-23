import pytest
from app.hasher import compute_hamming_distance, is_perceptual_match


def test_match_threshold_boundary():
    """
    Test 2 (Mandatory):
    Threshold boundary cases for perceptual matching.
    """
    base_hash = "8000000000000000"  # 64-bit hex (16 chars)

    # 1. Exact match (0 diff bits)
    match_0, dist_0 = is_perceptual_match(base_hash, base_hash, threshold=10)
    assert match_0 is True
    assert dist_0 == 0

    # 2. 10 bits difference (e.g., 0x03FF = 10 set bits: 1111111111)
    # XOR with 0x03FF produces distance 10
    hash_10 = hex(int(base_hash, 16) ^ 0x03FF)[2:].zfill(16)
    match_10, dist_10 = is_perceptual_match(base_hash, hash_10, threshold=10)
    assert dist_10 == 10
    assert match_10 is True, "Distance 10 must be recognized as a match (<= threshold)"

    # 3. 11 bits difference (0x07FF = 11 set bits)
    hash_11 = hex(int(base_hash, 16) ^ 0x07FF)[2:].zfill(16)
    match_11, dist_11 = is_perceptual_match(base_hash, hash_11, threshold=10)
    assert dist_11 == 11
    assert match_11 is False, "Distance 11 must NOT be recognized as a match (> threshold)"


def test_same_algorithm_enforcement():
    """
    Assert that comparing hashes of differing bit-lengths / formats raises an error.
    """
    h64 = "8000000000000000"
    h256 = "8000000000000000" * 4  # 64 hex chars (256 bits)

    with pytest.raises(ValueError) as excinfo:
        compute_hamming_distance(h64, h256)
    assert "Cannot compare hashes of different lengths" in str(excinfo.value)


def test_api_match_endpoint(client):
    """Test /v1/match via FastAPI client."""
    user_id = "test_user_42"

    # Register in vault
    base_hash = "8000000000000000"
    client.post("/v1/vault", json={
        "user_id": user_id,
        "phash": base_hash,
        "dhash": "0000000000000000",
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "label": "Original Profile"
    })

    # Close variation (dist 3)
    variant_hash = hex(int(base_hash, 16) ^ 0x07)[2:].zfill(16)
    res = client.post("/v1/match", json={
        "user_id": user_id,
        "hash_value": variant_hash,
        "algorithm": "phash"
    })
    assert res.status_code == 200
    data = res.json()
    assert len(data["matches"]) == 1
    assert data["matches"][0]["is_match"] is True
    assert data["matches"][0]["distance"] == 3

    # Far variation (dist 20)
    far_hash = hex(int(base_hash, 16) ^ 0xFFFFF)[2:].zfill(16)
    res_far = client.post("/v1/match", json={
        "user_id": user_id,
        "hash_value": far_hash,
        "algorithm": "phash"
    })
    assert res_far.status_code == 200
    data_far = res_far.json()
    assert data_far["matches"][0]["is_match"] is False
    assert data_far["matches"][0]["distance"] == 20
