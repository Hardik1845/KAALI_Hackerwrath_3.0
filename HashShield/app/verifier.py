import io
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
import httpx
from app.config import settings
from app.security import validate_hostname_ssrf, validate_image_bytes
from app.hasher import compute_hashes_from_bytes, compute_hamming_distance
from app.sscd import compute_sscd_embedding, compute_cosine_similarity
from app.models import CandidateMatchItem

logger = logging.getLogger("hashshield.verifier")


async def verify_single_candidate(
    candidate: Dict[str, Any],
    original_phash: str,
    original_dhash: str,
    original_sscd: Optional[List[float]] = None,
    timeout_sec: float = 5.0,
    max_mb: int = 5
) -> CandidateMatchItem:
    """
    Safely verifies a discovered image URL against the original perceptual hash.
    Enforces strict guards:
    - HTTPS only.
    - DNS resolution check against private/loopback/metadata IP ranges (before & after redirects).
    - Max 5 MB streaming limit.
    - Timeout of 5 seconds.
    - Magic bytes validation.
    - In-memory pHash/dHash comparison; bytes immediately discarded.
    """
    cand_id = candidate.get("candidate_id", "cand_unknown")
    page_url = candidate.get("page_url", "")
    image_url = candidate.get("image_url", "")
    domain = candidate.get("domain", "")
    match_type = candidate.get("match_type", "similar")

    # If candidate is a simulated synthetic in mock mode
    sim_type = candidate.get("simulated_synthetic")
    if sim_type:
        if sim_type == "master":
            return CandidateMatchItem(
                candidate_id=cand_id,
                page_url=page_url,
                image_url=image_url,
                domain=domain,
                match_type="full",
                verified=True,
                distance=0,
                note="Verified identical perceptual match (0 distance)"
            )
        elif sim_type == "derivative":
            return CandidateMatchItem(
                candidate_id=cand_id,
                page_url=page_url,
                image_url=image_url,
                domain=domain,
                match_type="partial",
                verified=True,
                distance=4,
                note="Verified partial/recompressed match (distance: 4 <= 10)"
            )
        elif sim_type == "unrelated":
            return CandidateMatchItem(
                candidate_id=cand_id,
                page_url=page_url,
                image_url=image_url,
                domain=domain,
                match_type="similar",
                verified=False,
                distance=28,
                note="Different image content (distance: 28 > 10)"
            )

    if not settings.FETCH_CANDIDATE_IMAGES:
        return CandidateMatchItem(
            candidate_id=cand_id,
            page_url=page_url,
            image_url=image_url,
            domain=domain,
            match_type=match_type,
            verified=None,
            note="Verification disabled; user to confirm"
        )

    # 1. Enforce HTTPS only
    if not image_url.lower().startswith("https://"):
        return CandidateMatchItem(
            candidate_id=cand_id,
            page_url=page_url,
            image_url=image_url,
            domain=domain,
            match_type=match_type,
            verified=None,
            note="Rejected: Non-HTTPS URL disallowed"
        )

    # 2. SSRF check on target host
    parsed = urlparse(image_url)
    hostname = parsed.hostname or ""
    is_safe, resolved_ips, ssrf_err = validate_hostname_ssrf(hostname)
    if not is_safe:
        return CandidateMatchItem(
            candidate_id=cand_id,
            page_url=page_url,
            image_url=image_url,
            domain=domain,
            match_type=match_type,
            verified=None,
            note=f"Rejected: SSRF safety check failed ({ssrf_err})"
        )

    # 3. Stream candidate image with strict byte limit and timeout
    max_bytes = max_mb * 1024 * 1024
    image_bytes = bytearray()

    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
            async with client.stream("GET", image_url) as response:
                if response.status_code != 200:
                    return CandidateMatchItem(
                        candidate_id=cand_id,
                        page_url=page_url,
                        image_url=image_url,
                        domain=domain,
                        match_type=match_type,
                        verified=None,
                        note=f"Fetch failed with HTTP {response.status_code}"
                    )

                # Check redirect safety
                final_host = urlparse(str(response.url)).hostname or ""
                safe_redirect, _, redirect_err = validate_hostname_ssrf(final_host)
                if not safe_redirect:
                    return CandidateMatchItem(
                        candidate_id=cand_id,
                        page_url=page_url,
                        image_url=image_url,
                        domain=domain,
                        match_type=match_type,
                        verified=None,
                        note=f"Rejected: Redirected to unsafe host ({redirect_err})"
                    )

                # Check Content-Type header
                c_type = response.headers.get("content-type", "").lower()
                if not any(t in c_type for t in ["image/jpeg", "image/png", "image/webp"]):
                    return CandidateMatchItem(
                        candidate_id=cand_id,
                        page_url=page_url,
                        image_url=image_url,
                        domain=domain,
                        match_type=match_type,
                        verified=None,
                        note=f"Rejected: Disallowed content-type '{c_type}'"
                    )

                # Stream chunks up to limit
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    image_bytes.extend(chunk)
                    if len(image_bytes) > max_bytes:
                        return CandidateMatchItem(
                            candidate_id=cand_id,
                            page_url=page_url,
                            image_url=image_url,
                            domain=domain,
                            match_type=match_type,
                            verified=None,
                            note=f"Rejected: Candidate file exceeds size limit of {max_mb} MB"
                        )

        # 4. In-memory validation & pHash computation
        raw_data = bytes(image_bytes)
        hashes = compute_hashes_from_bytes(raw_data, max_mb=max_mb)
        cand_phash = hashes["phash"]

        # 5. Hamming distance comparison
        dist = compute_hamming_distance(original_phash, cand_phash)
        phash_match = (dist <= settings.HASH_THRESHOLD)

        # 6. Optional Neural SSCD feature comparison
        cand_similarity = None
        sscd_match = False
        if settings.ENABLE_SSCD and original_sscd:
            cand_sscd = compute_sscd_embedding(raw_data)
            if cand_sscd:
                cand_similarity = compute_cosine_similarity(original_sscd, cand_sscd)
                sscd_match = (cand_similarity >= settings.SSCD_SIMILARITY_THRESHOLD)

        is_match = phash_match or sscd_match
        note_parts = [f"Hamming: {dist} (<= {settings.HASH_THRESHOLD})"]
        if cand_similarity is not None:
            note_parts.append(f"SSCD: {cand_similarity:.4f} (>= {settings.SSCD_SIMILARITY_THRESHOLD})")

        return CandidateMatchItem(
            candidate_id=cand_id,
            page_url=page_url,
            image_url=image_url,
            domain=domain,
            match_type=match_type,
            verified=is_match,
            distance=dist,
            similarity=cand_similarity,
            sscd_verified=sscd_match if cand_similarity is not None else None,
            note=" | ".join(note_parts)
        )

    except Exception as e:
        logger.warning(f"Error verifying candidate {image_url}: {e}")
        return CandidateMatchItem(
            candidate_id=cand_id,
            page_url=page_url,
            image_url=image_url,
            domain=domain,
            match_type=match_type,
            verified=None,
            note=f"Verification error: {str(e)}"
        )


async def verify_candidates(
    candidates: List[Dict[str, Any]],
    original_phash: str,
    original_dhash: str,
    original_sscd: Optional[List[float]] = None,
    max_verify: int = 20
) -> List[CandidateMatchItem]:
    """Verify up to max_verify candidates concurrently with safe guards."""
    items_to_verify = candidates[:max_verify]
    verified_items: List[CandidateMatchItem] = []

    for cand in items_to_verify:
        res = await verify_single_candidate(
            cand,
            original_phash,
            original_dhash,
            original_sscd=original_sscd,
            timeout_sec=settings.CANDIDATE_FETCH_TIMEOUT,
            max_mb=settings.CANDIDATE_MAX_MB
        )
        verified_items.append(res)

    # Sort: verified=True first, lowest distance first
    def sort_key(item: CandidateMatchItem):
        v_order = 0 if item.verified is True else (1 if item.verified is None else 2)
        d_val = item.distance if item.distance is not None else 999
        return (v_order, d_val)

    verified_items.sort(key=sort_key)
    return verified_items
