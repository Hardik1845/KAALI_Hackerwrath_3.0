import uuid
import logging
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.models import (
    HashResponse, VaultRegisterRequest, VaultItem,
    MatchRequest, MatchResponse, MatchResultItem,
    CaseCreateRequest, CaseSentResponse, CaseResolveRequest, CaseResolveResponse,
    CaseNoticeResponse, CaseDetailResponse, LookupResultItem,
    ScanResponse, CandidateMatchItem, CaseCreateFromCandidatesRequest,
    CaseCheckResponse, DueJobsResponse, DueJobItem
)
from app.security import verify_api_key, limiter
from app.hasher import compute_hashes_from_bytes, compute_hamming_distance, is_perceptual_match
from app.rdap import lookup_domain_rdap
from app.notices import render_notice_texts, generate_notice_pdf
from app.storage import storage
from app.discovery import get_discovery_provider, discovery_cache
from app.verifier import verify_candidates
from app.checker import check_case_urls

# Configure structured logging without sensitive data
logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("hashshield.api")

# FastAPI Application
app = FastAPI(
    title="Hash Shield Microservice — Project KAALI",
    description=(
        "Zero-knowledge privacy-preserving evidence collection, perceptual hashing, "
        "reverse web discovery, host RDAP lookup, and statutory 24-hour takedown engine for Project KAALI."
    ),
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# SlowAPI setup
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4173", "http://localhost:4173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    """Inject a unique request-id header for structured tracing."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ==============================================================================
# LIVENESS & HEALTH
# ==============================================================================

@app.get("/health", tags=["System"])
async def health_check():
    """Liveness probe returning service operational status."""
    return {
        "status": "ok",
        "service": "HashShield",
        "version": "1.1.0",
        "web_search_provider": settings.DISCOVER_PROVIDER,
        "web_search_configured": (
            (settings.DISCOVER_PROVIDER.lower() in ("serpapi", "serpapi_lens") and bool(settings.SERPAPI_API_KEY))
            or (settings.DISCOVER_PROVIDER.lower() == "google_vision" and bool(settings.GOOGLE_APPLICATION_CREDENTIALS))
        ),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ==============================================================================
# DISCOVERY & WEB SCANNING (FLOW STEP 1)
# ==============================================================================

@app.post(
    "/v1/scan",
    response_model=ScanResponse,
    tags=["Discovery & Scanning"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("20/minute")
async def scan_image(
    request: Request,
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None, description="Public image URL to reverse search (recommended for SerpApi Google Lens)"),
    consent: bool = Form(False, description="Explicit user consent to send this image to the configured web discovery provider"),
    intimate: bool = Form(False, description="Whether the original is an intimate/explicit image"),
    is_minor: bool = Form(False, description="Whether the original involves a person under 18")
):
    """
    Step 1: Upload original photo or public image URL → compute in-memory perceptual hashes → run web discovery.
    HARD RULES:
    1. Consent is required.
    2. If is_minor=True: Immediately halt and provide statutory child protection links (1098 / cybercrime.gov.in).
    3. If intimate=True: Do NOT scan third-party web engines. Return StopNCII instructions and allow manual URLs.
    4. If intimate=False: Run discovery provider, safely verify up to 20 candidates, and rank them.
    5. Image bytes are never stored on disk.
    """
    if is_minor:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cases involving minors cannot be processed automatically. Please report immediately to Childline 1098 and the National Cyber Crime Reporting Portal (https://cybercrime.gov.in)."
        )

    if not consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User consent is strictly required to scan the web."
        )

    try:
        # Sanitize Swagger UI default placeholder
        if image_url in ("string", "", None):
            image_url = None

        if file is not None and getattr(file, "filename", None):
            data = await file.read()
        elif image_url:
            import httpx
            from app.security import validate_hostname_ssrf
            parsed = urlparse(image_url)
            is_safe, _, err = validate_hostname_ssrf(parsed.hostname or "")
            if not is_safe:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Image URL rejected by SSRF guard: {err}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                res_fetch = await client.get(image_url)
                if res_fetch.status_code != 200:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to fetch image_url: HTTP {res_fetch.status_code}")
                data = res_fetch.content
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either 'file' or 'image_url' must be provided.")

        res = compute_hashes_from_bytes(data, max_mb=settings.UPLOAD_MAX_MB)
        original_id = f"orig_{uuid.uuid4().hex[:12]}"
        phash = res["phash"]
        dhash = res["dhash"]
        sha256 = res["sha256"]

        # Compute neural SSCD descriptor if enabled
        original_sscd = None
        if settings.ENABLE_SSCD:
            try:
                from app.sscd import compute_sscd_embedding
                original_sscd = compute_sscd_embedding(data)
            except Exception as se:
                logger.warning(f"Could not compute original SSCD embedding: {se}")

        # Branch A: Intimate image -> StopNCII Protocol hand-off (do NOT scan web)
        if intimate:
            logger.info(f"Intimate image flagged ({original_id}). Skipping external web scan per privacy mandate.")
            stop_ncii_info = {
                "url": "https://stopncii.org",
                "message": (
                    "To safeguard your privacy, intimate imagery is NEVER transmitted to external web search engines. "
                    "Please register your perceptual hash directly with the StopNCII.org coalition (Meta, TikTok, OnlyFans, etc.) "
                    "or manually input suspected infringing URLs below to draft takedown notices."
                ),
                "instructions": [
                    "1. Visit https://stopncii.org directly from your browser.",
                    "2. Upload your image to generate an on-device privacy-preserving hash.",
                    "3. Submit hash to participating platforms for automated preemptive blocking.",
                    "4. If you have specific URLs where your image is hosted, paste them into 'Create Case' for 24h statutory takedown."
                ]
            }

            # Save scan record
            scan_doc = {
                "original_id": original_id,
                "phash": phash,
                "dhash": dhash,
                "sha256": sha256,
                "intimate": True,
                "candidates": [],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            await storage.save_scan(scan_doc)

            return ScanResponse(
                original_id=original_id,
                phash=phash,
                dhash=dhash,
                sha256=sha256,
                intimate=True,
                candidates=[],
                stop_ncii=stop_ncii_info,
                daily_scans_remaining=discovery_cache.get_remaining_quota(settings.DISCOVER_DAILY_LIMIT),
                sscd_embedding=original_sscd
            )

        # Branch B: Non-intimate image -> Run Web Discovery & Verification
        try:
            remaining_quota = discovery_cache.check_and_increment_daily_quota(settings.DISCOVER_DAILY_LIMIT)
        except ValueError as qe:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(qe))

        # Check 24h cache
        cached_candidates = discovery_cache.get(phash)
        if cached_candidates is not None:
            raw_candidates = cached_candidates
            logger.info(f"Retrieved {len(raw_candidates)} candidates from 24h discovery cache.")
        else:
            provider = get_discovery_provider()
            try:
                raw_candidates = await provider.discover(data, phash, image_url=image_url)
            except RuntimeError as provider_error:
                raise HTTPException(status_code=503, detail=str(provider_error)) from provider_error
            discovery_cache.set(phash, raw_candidates)
            logger.info(f"Discovered {len(raw_candidates)} candidates via provider '{settings.DISCOVER_PROVIDER}'.")

        # Verify candidates with safe in-memory guards and SSCD embeddings
        verified_candidates = await verify_candidates(
            raw_candidates,
            original_phash=phash,
            original_dhash=dhash,
            original_sscd=original_sscd,
            max_verify=settings.MAX_CANDIDATES_TO_VERIFY
        )

        scan_doc = {
            "original_id": original_id,
            "phash": phash,
            "dhash": dhash,
            "sha256": sha256,
            "intimate": False,
            "candidates": [c.model_dump() for c in verified_candidates],
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await storage.save_scan(scan_doc)

        return ScanResponse(
            original_id=original_id,
            phash=phash,
            dhash=dhash,
            sha256=sha256,
            intimate=False,
            candidates=verified_candidates,
            stop_ncii=None,
            daily_scans_remaining=remaining_quota,
            sscd_embedding=original_sscd
        )

    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"Scan error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Scan failed: {str(e)}")


# ==============================================================================
# HASHING & ZERO-KNOWLEDGE EVIDENCE
# ==============================================================================

@app.post(
    "/v1/hash",
    response_model=HashResponse,
    tags=["Hashing"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("30/minute")
async def hash_image(
    request: Request,
    file: UploadFile = File(...)
):
    """
    Process an uploaded image entirely in memory.
    Inspects magic bytes, computes pHash, dHash, SHA-256 and dimensions, then discards image bytes.
    Never stores image bytes on disk.
    """
    try:
        data = await file.read()
        res = compute_hashes_from_bytes(data, max_mb=settings.UPLOAD_MAX_MB)
        logger.info(f"Image hashed in memory. Dimensions: {res['width']}x{res['height']}")
        return HashResponse(
            phash=res["phash"],
            dhash=res["dhash"],
            sha256=res["sha256"],
            width=res["width"],
            height=res["height"]
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"Hashing error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process image")


# ==============================================================================
# PERCEPTUAL HASH VAULT
# ==============================================================================

@app.post(
    "/v1/vault",
    response_model=VaultItem,
    tags=["Vault"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("30/minute")
async def register_vault_hash(
    request: Request,
    req: VaultRegisterRequest
):
    """
    Register an authentic reference photo's perceptual fingerprints in a victim's private vault.
    Stores only hashes, timestamp, and optional user label.
    """
    vault_id = f"v_{uuid.uuid4().hex[:12]}"
    item = VaultItem(
        vault_id=vault_id,
        user_id=req.user_id,
        phash=req.phash.strip().lower(),
        dhash=req.dhash.strip().lower(),
        sha256=req.sha256.strip().lower(),
        label=req.label,
        created_at=datetime.now(timezone.utc).isoformat()
    )
    await storage.save_vault_item(item)
    logger.info(f"Registered vault entry {vault_id} for user {req.user_id}")
    return item


@app.post(
    "/v1/match",
    response_model=MatchResponse,
    tags=["Matching"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("60/minute")
async def match_hash(
    request: Request,
    user_id: str = Form(None),
    hash_value: str = Form(None),
    algorithm: str = Form("phash"),
    file: Optional[UploadFile] = File(None)
):
    """
    Compare a suspect image (or provided hash) against all registered hashes in the user's vault.
    Strictly compares hashes from the same algorithm using Hamming distance.
    Threshold default: 10 bits.
    """
    # Fallback to JSON body if not multipart
    if not user_id:
        try:
            body = await request.json()
            user_id = body.get("user_id")
            hash_value = body.get("hash_value")
            algorithm = body.get("algorithm", "phash")
        except Exception:
            pass

    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user_id parameter")

    # If file was uploaded in request, hash it in memory
    if file:
        try:
            data = await file.read()
            res = compute_hashes_from_bytes(data, max_mb=settings.UPLOAD_MAX_MB)
            hash_value = res.get(algorithm, res["phash"])
        except ValueError as ve:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    if not hash_value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Must provide either hash_value or image file")

    algorithm = algorithm.lower().strip()
    if algorithm not in {"phash", "dhash"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Algorithm must be 'phash' or 'dhash'")

    vault_items = await storage.get_vault_items(user_id)
    matches: List[MatchResultItem] = []

    for item in vault_items:
        vault_hash = item.phash if algorithm == "phash" else item.dhash
        try:
            is_match, dist = is_perceptual_match(hash_value, vault_hash, threshold=settings.HASH_THRESHOLD)
            matches.append(MatchResultItem(
                vault_id=item.vault_id,
                algorithm=algorithm,
                distance=dist,
                is_match=is_match,
                label=item.label
            ))
        except ValueError as ve:
            logger.warning(f"Skipping hash comparison due to format mismatch: {ve}")

    return MatchResponse(
        matches=matches,
        threshold=settings.HASH_THRESHOLD,
        note="Perceptual hashes can be evaded by heavy edits; absence of a match is not proof."
    )


# ==============================================================================
# CASE MANAGEMENT & RECOVERY
# ==============================================================================

@app.post(
    "/v1/cases",
    response_model=CaseDetailResponse,
    tags=["Cases"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("30/minute")
async def create_case(
    request: Request
):
    """
    Initialize an evidence recovery and takedown case.
    Accepts either:
    1. Legacy CaseCreateRequest ({user_id, urls[], evidence_hashes[], notes, is_minor})
    2. CaseCreateFromCandidatesRequest ({user_id, original_id, candidate_ids[], manual_urls[], notes, is_minor})
    Strict under-18 safety check: Immediately rejects if minor involvement is flagged.
    """
    body = await request.json()

    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user_id")

    is_minor = body.get("is_minor", False)
    notes = body.get("notes")

    # Minor check
    if is_minor:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Under-18 Safety Violation: This service cannot process reports involving persons under 18. "
                "Please immediately report to specialized child protection authorities: "
                "National Cyber Crime Reporting Portal (cybercrime.gov.in) or Childline 1098."
            )
        )

    if notes:
        note_lower = notes.lower()
        minor_keywords = ["minor", "under 18", "child", "underage", "16 year", "17 year"]
        if any(kw in note_lower for kw in minor_keywords):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Under-18 Safety Violation: Keywords indicating a minor were detected in case notes. "
                    "This service cannot process reports involving persons under 18. "
                    "Please immediately report to specialized child protection authorities: "
                    "National Cyber Crime Reporting Portal (cybercrime.gov.in) or Childline 1098."
                )
            )

    urls: List[str] = list(body.get("urls") or [])
    evidence_hashes: List[str] = list(body.get("evidence_hashes") or [])

    # Support candidate selection from scan
    original_id = body.get("original_id")
    candidate_ids = body.get("candidate_ids") or []
    manual_urls = body.get("manual_urls") or []
    urls.extend(manual_urls)

    if original_id:
        scan_doc = await storage.get_scan(original_id)
        if scan_doc:
            if scan_doc.get("phash"):
                evidence_hashes.append(f"phash_{scan_doc['phash']}")
            if scan_doc.get("sha256"):
                evidence_hashes.append(f"sha256_{scan_doc['sha256']}")

            # Extract URLs for matching candidate IDs
            if candidate_ids:
                cand_map = {c["candidate_id"]: c for c in scan_doc.get("candidates", [])}
                for cid in candidate_ids:
                    if cid in cand_map:
                        cand_url = cand_map[cid].get("page_url") or cand_map[cid].get("image_url")
                        if cand_url and cand_url not in urls:
                            urls.append(cand_url)

    # Deduplicate URLs
    clean_urls = list(dict.fromkeys([u.strip() for u in urls if u and u.strip()]))

    case_id = f"case_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    case_doc = {
        "case_id": case_id,
        "user_id": user_id,
        "status": "created",
        "urls": clean_urls,
        "evidence_hashes": evidence_hashes,
        "notes": notes,
        "lookups": [],
        "sent_at": None,
        "deadline": None,
        "due_at": None,
        "created_at": now_iso,
        "updated_at": now_iso
    }

    await storage.save_case(case_doc)
    logger.info(f"Created new case {case_id} for user {user_id} with {len(clean_urls)} target URLs")
    return CaseDetailResponse(**case_doc)


@app.post(
    "/v1/cases/{case_id}/lookup",
    response_model=CaseDetailResponse,
    tags=["Cases"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("20/minute")
async def lookup_case_hosts(
    request: Request,
    case_id: str
):
    """
    Performs SSRF-safe RDAP and DNS lookup for each URL in the case.
    Identifies domain registrar, hosting provider, and abuse desk contact emails.
    If behind Cloudflare, returns its abuse form link (https://abuse.cloudflare.com).
    """
    case = await storage.get_case(case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    urls = case.get("urls", [])
    lookups: List[LookupResultItem] = []

    for u in urls:
        res = await lookup_domain_rdap(u)
        lookups.append(res)

    updated_case = await storage.update_case(case_id, {
        "lookups": [lk.model_dump() for lk in lookups]
    })

    return CaseDetailResponse(**updated_case)


@app.post(
    "/v1/cases/{case_id}/notices",
    response_model=CaseNoticeResponse,
    tags=["Cases"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("20/minute")
async def generate_case_notices(
    request: Request,
    case_id: str
):
    """
    Compiles statutory plain-text notice templates and generates an evidence PDF document.
    Includes visible '[TODO: verify legal wording]' marker and references Rule 3(2)(b) IT Rules 2021.
    """
    case = await storage.get_case(case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    text_notices = render_notice_texts(case)
    pdf_b64 = generate_notice_pdf(case)

    evidence_sha256 = (
        case.get("evidence_hashes", [""])[0]
        if case.get("evidence_hashes")
        else "0x0000000000000000"
    )

    return CaseNoticeResponse(
        case_id=case_id,
        notices=text_notices,
        pdf_base64=pdf_b64,
        evidence_sha256=evidence_sha256,
        todo_marker="TODO: verify legal wording"
    )


@app.post(
    "/v1/cases/{case_id}/sent",
    response_model=CaseSentResponse,
    tags=["Cases"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("20/minute")
async def mark_case_sent(
    request: Request,
    case_id: str
):
    """
    Victim marks that she has dispatched the statutory notice herself.
    Sets due_at deadline and starts the statutory SLA timer (default: 24 hours).
    """
    case = await storage.get_case(case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    now = datetime.now(timezone.utc)
    due_at_dt = now + timedelta(hours=settings.SLA_HOURS)

    sent_at_iso = now.isoformat()
    due_at_iso = due_at_dt.isoformat()

    await storage.update_case(case_id, {
        "status": "sent",
        "sent_at": sent_at_iso,
        "due_at": due_at_iso,
        "deadline": due_at_iso
    })

    return CaseSentResponse(
        case_id=case_id,
        status="sent",
        sent_at=sent_at_iso,
        sla_hours=settings.SLA_HOURS,
        deadline=due_at_iso
    )


@app.post(
    "/v1/cases/{case_id}/check",
    response_model=CaseCheckResponse,
    tags=["Cases"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("20/minute")
async def check_case_removal_status(
    request: Request,
    case_id: str
):
    """
    Probes each URL in the case using non-destructive HEAD/GET requests with discarded bodies.
    Detects HTTP 404/410 (likely removed) vs HTTP 200/403 (inconclusive).
    Never trusts alone; user must verify before closure.
    """
    case = await storage.get_case(case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    urls = case.get("urls", [])
    report = await check_case_urls(case_id, urls)
    return report


@app.get(
    "/v1/cases/{case_id}",
    response_model=CaseDetailResponse,
    tags=["Cases"],
    dependencies=[Depends(verify_api_key)]
)
async def get_case_status(
    case_id: str
):
    """
    Retrieve full case details, evidence index, and remaining SLA timer countdown evaluated from due_at on read.
    """
    case = await storage.get_case(case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    # Compute remaining time if sent
    seconds_remaining = None
    target_deadline = case.get("due_at") or case.get("deadline")
    if target_deadline:
        try:
            deadline_dt = datetime.fromisoformat(target_deadline)
            now_dt = datetime.now(timezone.utc)
            delta = (deadline_dt - now_dt).total_seconds()
            seconds_remaining = max(0.0, delta)
        except Exception:
            pass

    case_dict = dict(case)
    case_dict["seconds_remaining"] = seconds_remaining

    return CaseDetailResponse(**case_dict)


@app.get(
    "/v1/jobs/due",
    response_model=DueJobsResponse,
    tags=["System"],
    dependencies=[Depends(verify_api_key)]
)
async def get_due_jobs():
    """
    Endpoint for external cron jobs to inspect cases where the statutory 24-hour SLA has expired.
    """
    due_cases = await storage.get_due_cases()
    now = datetime.now(timezone.utc)
    jobs: List[DueJobItem] = []

    for c in due_cases:
        due_at_str = c.get("due_at") or c.get("deadline")
        overdue_sec = 0.0
        if due_at_str:
            try:
                due_dt = datetime.fromisoformat(due_at_str)
                overdue_sec = max(0.0, (now - due_dt).total_seconds())
            except Exception:
                pass
        jobs.append(DueJobItem(
            case_id=c["case_id"],
            user_id=c["user_id"],
            due_at=due_at_str or "",
            overdue_seconds=overdue_sec
        ))

    return DueJobsResponse(count=len(jobs), jobs=jobs)


@app.post(
    "/v1/cases/{case_id}/resolve",
    response_model=CaseResolveResponse,
    tags=["Cases"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("20/minute")
async def resolve_case(
    request: Request,
    case_id: str,
    req: CaseResolveRequest
):
    """
    Resolve the case based on whether infringing material was removed within SLA.
    If removed: Closes case and preserves evidence log.
    If not removed: Sets status to 'escalated' and returns complete escalation packet
    (cybercrime.gov.in, helpline 1930, and StopNCII hand-off).
    """
    case = await storage.get_case(case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    now_iso = datetime.now(timezone.utc).isoformat()

    if req.removed:
        await storage.update_case(case_id, {
            "status": "closed",
            "resolved_at": now_iso
        })
        return CaseResolveResponse(
            case_id=case_id,
            status="closed",
            resolved_at=now_iso,
            escalation=None
        )
    else:
        escalation_payload = {
            "portal": "https://cybercrime.gov.in",
            "helpline": "1930",
            "recommendation": (
                "Intermediary failed to remove non-consensual content within the statutory 24-hour SLA. "
                "Safe harbor under Section 79(1) of the Information Technology Act is extinguished. "
                "Download the PDF Evidence Dossier and file a formal FIR under IT Act Sections 66E/67A and IPC/BNS."
            ),
            "stop_ncii": {
                "url": "https://stopncii.org",
                "instructions": (
                    "StopNCII.org operates an independent hash-sharing coalition with participating tech platforms. "
                    "Visit stopncii.org directly from your browser to register your image hashes with their global network."
                )
            }
        }
        await storage.update_case(case_id, {
            "status": "escalated",
            "resolved_at": now_iso
        })
        return CaseResolveResponse(
            case_id=case_id,
            status="escalated",
            resolved_at=now_iso,
            escalation=escalation_payload
        )
