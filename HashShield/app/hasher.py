import io
import hashlib
from typing import Tuple, Dict, Any
from PIL import Image
import imagehash
from app.security import validate_image_bytes


def compute_hashes_from_bytes(data: bytes, max_mb: int = 10) -> Dict[str, Any]:
    """
    Validates magic bytes, reads image strictly in memory, computes hashes,
    and returns metadata dictionary while immediately releasing memory.
    Never stores image bytes on disk.
    """
    is_valid, mime_type, err = validate_image_bytes(data, max_mb=max_mb)
    if not is_valid:
        raise ValueError(err)

    # Compute cryptographic SHA-256
    sha256_digest = hashlib.sha256(data).hexdigest()

    # In-memory buffer
    buf = io.BytesIO(data)
    try:
        with Image.open(buf) as img:
            # Force decode into memory
            img.load()
            width, height = img.size

            # Compute perceptual hashes
            ph = str(imagehash.phash(img))
            dh = str(imagehash.dhash(img))

            return {
                "phash": ph,
                "dhash": dh,
                "sha256": sha256_digest,
                "width": width,
                "height": height,
                "mime_type": mime_type
            }
    finally:
        buf.close()


def compute_hamming_distance(hash1: str, hash2: str) -> int:
    """
    Computes bitwise Hamming distance between two hexadecimal hash strings.
    Validates that the hashes belong to the same algorithm and length.
    """
    clean1 = hash1.strip().lower()
    clean2 = hash2.strip().lower()

    if len(clean1) != len(clean2):
        raise ValueError(
            f"Cannot compare hashes of different lengths: {len(clean1)} vs {len(clean2)}. "
            "Ensure both hashes use the same algorithm (e.g. pHash to pHash)."
        )

    val1 = int(clean1, 16)
    val2 = int(clean2, 16)
    xor_val = val1 ^ val2
    return bin(xor_val).count('1')


def is_perceptual_match(hash1: str, hash2: str, threshold: int = 10) -> Tuple[bool, int]:
    """
    Returns (is_match, distance) for two hashes given a threshold.
    """
    dist = compute_hamming_distance(hash1, hash2)
    return (dist <= threshold, dist)
