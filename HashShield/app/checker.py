import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from urllib.parse import urlparse
import httpx
from app.models import CaseCheckResultItem, CaseCheckResponse
from app.security import validate_hostname_ssrf

logger = logging.getLogger("hashshield.checker")


async def check_url_removal(url: str, timeout_sec: float = 3.5) -> CaseCheckResultItem:
    """
    Safely probes an infringing URL to assess whether it has been removed.
    Sends HEAD request; falls back to GET with stream (body discarded).
    Status codes 404 or 410 -> likely_removed.
    Status codes 200, 403, 500 etc -> inconclusive.
    Never trusts alone; user must confirm.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    is_safe, _, ssrf_err = validate_hostname_ssrf(hostname)
    if not is_safe:
        return CaseCheckResultItem(
            url=url,
            status_code=None,
            removed_assessment="inconclusive",
            checked_at=now_iso,
            note=f"Probe skipped due to SSRF block: {ssrf_err}"
        )

    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
            status_code = None
            try:
                # 1. Try HEAD request
                head_res = await client.head(url)
                status_code = head_res.status_code
            except Exception:
                pass

            # 2. Fallback to GET if HEAD failed or was method-not-allowed (405)
            if status_code is None or status_code == 405:
                async with client.stream("GET", url) as get_res:
                    status_code = get_res.status_code
                    # Body is intentionally NOT read and discarded

            if status_code in (404, 410):
                assessment = "likely_removed"
                note = f"HTTP {status_code} indicates page or asset has been taken down."
            elif status_code == 200:
                assessment = "inconclusive"
                note = "HTTP 200 OK received; content may still be live. User confirmation required."
            elif status_code in (403, 401):
                assessment = "inconclusive"
                note = f"HTTP {status_code} received; access restricted or protected. Verify manually."
            else:
                assessment = "inconclusive"
                note = f"HTTP {status_code} received; inconclusive state."

            return CaseCheckResultItem(
                url=url,
                status_code=status_code,
                removed_assessment=assessment,
                checked_at=now_iso,
                note=note
            )

    except Exception as e:
        return CaseCheckResultItem(
            url=url,
            status_code=None,
            removed_assessment="inconclusive",
            checked_at=now_iso,
            note=f"Connection error or timeout ({str(e)}). State inconclusive."
        )


async def check_case_urls(case_id: str, urls: List[str]) -> CaseCheckResponse:
    """Checks all URLs for a given case and compiles report."""
    results = []
    for u in urls:
        item = await check_url_removal(u)
        results.append(item)

    return CaseCheckResponse(
        case_id=case_id,
        results=results,
        advice="Automated probes (404/410) are indicative; user confirmation is required before closing case."
    )
