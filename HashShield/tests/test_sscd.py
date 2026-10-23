import io
import pytest
from PIL import Image, ImageDraw
from app.sscd import compute_sscd_embedding, compute_cosine_similarity, is_sscd_match
from app.config import settings


def test_sscd_embedding_generation(sample_image_bytes):
    embedding = compute_sscd_embedding(sample_image_bytes)
    assert embedding is not None
    assert len(embedding) == 576
    # Check L2 unit norm
    import numpy as np
    norm = np.linalg.norm(np.array(embedding, dtype=np.float32))
    assert pytest.approx(norm, rel=1e-3) == 1.0


def test_sscd_cosine_similarity_discrimination(sample_image_bytes, unrelated_image_bytes):
    emb_orig = compute_sscd_embedding(sample_image_bytes)
    emb_unrel = compute_sscd_embedding(unrelated_image_bytes)

    # Identical match
    self_sim = compute_cosine_similarity(emb_orig, emb_orig)
    assert pytest.approx(self_sim, rel=1e-3) == 1.0

    # Unrelated images should have low similarity (< 0.60)
    unrel_sim = compute_cosine_similarity(emb_orig, emb_unrel)
    assert unrel_sim < 0.60
    assert not is_sscd_match(emb_orig, emb_unrel, threshold=settings.SSCD_SIMILARITY_THRESHOLD)

    # Derivative: Create cropped & recompressed copy
    img = Image.open(io.BytesIO(sample_image_bytes)).convert("RGB")
    cropped = img.crop((20, 20, 180, 180)).resize((120, 120))
    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=60)
    emb_crop = compute_sscd_embedding(buf.getvalue())

    crop_sim = compute_cosine_similarity(emb_orig, emb_crop)
    # Cropped derivative should have high similarity (>= 0.70)
    assert crop_sim >= 0.70
    assert is_sscd_match(emb_orig, emb_crop, threshold=settings.SSCD_SIMILARITY_THRESHOLD)


def test_scan_endpoint_includes_sscd(client, sample_image_bytes):
    response = client.post(
        "/v1/scan",
        files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")},
        data={"consent": "true", "intimate": "false", "is_minor": "false"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "sscd_embedding" in data
    assert data["sscd_embedding"] is not None
    assert len(data["sscd_embedding"]) == 576
