import io
from PIL import Image
from app.hasher import compute_hashes_from_bytes, compute_hamming_distance, is_perceptual_match
from app.config import settings


def test_hash_stability(sample_image_bytes, unrelated_image_bytes):
    """
    Test 1 (Mandatory):
    The same image recompressed (JPEG quality 70), resized to 50%, and lightly cropped
    stays within the threshold (distance <= 10); an unrelated image does not.
    """
    # 1. Compute original hash
    orig_res = compute_hashes_from_bytes(sample_image_bytes)
    orig_phash = orig_res["phash"]

    # 2. Recompress (Quality 70)
    img_orig = Image.open(io.BytesIO(sample_image_bytes))
    buf_recompressed = io.BytesIO()
    img_orig.save(buf_recompressed, format="JPEG", quality=70)
    recomp_res = compute_hashes_from_bytes(buf_recompressed.getvalue())
    recomp_phash = recomp_res["phash"]

    dist_recomp = compute_hamming_distance(orig_phash, recomp_phash)
    assert dist_recomp <= settings.HASH_THRESHOLD, f"Recompressed distance {dist_recomp} exceeded threshold {settings.HASH_THRESHOLD}"

    # 3. Resize to 50%
    w, h = img_orig.size
    img_resized = img_orig.resize((w // 2, h // 2))
    buf_resized = io.BytesIO()
    img_resized.save(buf_resized, format="JPEG", quality=90)
    resized_res = compute_hashes_from_bytes(buf_resized.getvalue())
    dist_resized = compute_hamming_distance(orig_phash, resized_res["phash"])
    assert dist_resized <= settings.HASH_THRESHOLD, f"Resized distance {dist_resized} exceeded threshold {settings.HASH_THRESHOLD}"

    # 4. Light crop (5% margin off edges)
    crop_box = (int(w * 0.05), int(h * 0.05), int(w * 0.95), int(h * 0.95))
    img_cropped = img_orig.crop(crop_box)
    buf_cropped = io.BytesIO()
    img_cropped.save(buf_cropped, format="JPEG", quality=90)
    cropped_res = compute_hashes_from_bytes(buf_cropped.getvalue())
    dist_cropped = compute_hamming_distance(orig_phash, cropped_res["phash"])
    assert dist_cropped <= settings.HASH_THRESHOLD, f"Cropped distance {dist_cropped} exceeded threshold {settings.HASH_THRESHOLD}"

    # 5. Unrelated image must NOT match (distance > 10)
    unrelated_res = compute_hashes_from_bytes(unrelated_image_bytes)
    dist_unrelated = compute_hamming_distance(orig_phash, unrelated_res["phash"])
    assert dist_unrelated > settings.HASH_THRESHOLD, f"Unrelated image distance {dist_unrelated} unexpectedly matched threshold {settings.HASH_THRESHOLD}"
