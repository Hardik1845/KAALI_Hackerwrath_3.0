from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import datetime


class HashResponse(BaseModel):
    """Response returned after computing perceptual and cryptographic hashes."""
    phash: str = Field(..., description="256-bit or 64-bit hexadecimal pHash")
    dhash: str = Field(..., description="64-bit hexadecimal dHash")
    sha256: str = Field(..., description="Cryptographic SHA-256 digest")
    width: int = Field(..., description="Image width in pixels")
    height: int = Field(..., description="Image height in pixels")


class VaultRegisterRequest(BaseModel):
    """Request to register a victim's authentic reference photo hashes."""
    user_id: str = Field(..., description="Unique victim or client identifier")
    phash: str = Field(..., description="pHash string")
    dhash: str = Field(..., description="dHash string")
    sha256: str = Field(..., description="Cryptographic SHA-256 fingerprint")
    label: Optional[str] = Field(None, description="Optional label for the vault entry")


class VaultItem(BaseModel):
    """Stored vault entry representing a protected image fingerprint."""
    vault_id: str
    user_id: str
    phash: str
    dhash: str
    sha256: str
    label: Optional[str] = None
    created_at: str


class MatchRequest(BaseModel):
    """Query to check similarity between an incoming hash and a user's vault."""
    user_id: str = Field(..., description="User ID whose vault should be matched")
    hash_value: Optional[str] = Field(None, description="Hexadecimal hash string to compare")
    algorithm: str = Field("phash", description="Algorithm to compare: 'phash' or 'dhash'")


class MatchResultItem(BaseModel):
    """Individual match entry against a vault item."""
    vault_id: str
    algorithm: str
    distance: int
    is_match: bool
    label: Optional[str] = None


class MatchResponse(BaseModel):
    """Match response payload."""
    matches: List[MatchResultItem]
    threshold: int
    note: str = "Perceptual hashes can be evaded by heavy edits; absence of a match is not proof."


class CaseCreateRequest(BaseModel):
    """Create a new takedown / recovery case."""
    user_id: str
    urls: List[str]
    evidence_hashes: List[str]
    notes: Optional[str] = None
    is_minor: bool = Field(False, description="Whether the case involves a person under 18")


class LookupResultItem(BaseModel):
    """RDAP / DNS lookup result for an individual URL."""
    url: str
    domain: str
    registrar: Optional[str] = None
    host: Optional[str] = None
    abuse_emails: List[str] = []
    cloudflare_abuse_url: Optional[str] = None
    status: str = "found"  # 'found' | 'not_found' | 'error'
    error_detail: Optional[str] = None


class CaseNoticeResponse(BaseModel):
    """Notice generation response with text templates and PDF bytes."""
    case_id: str
    notices: Dict[str, str]
    pdf_base64: str
    evidence_sha256: str
    todo_marker: str = "TODO: verify legal wording"


class CaseSentResponse(BaseModel):
    """Response when a user marks a takedown notice as dispatched."""
    case_id: str
    status: str
    sent_at: str
    sla_hours: int
    deadline: str


class CaseResolveRequest(BaseModel):
    """Case resolution request."""
    removed: bool = Field(..., description="True if content removed, False if content remains")


class CaseResolveResponse(BaseModel):
    """Case resolution response."""
    case_id: str
    status: str
    resolved_at: str
    escalation: Optional[Dict[str, Any]] = None


class CaseDetailResponse(BaseModel):
    """Complete case representation."""
    case_id: str
    user_id: str
    status: str  # 'created' | 'sent' | 'closed' | 'escalated'
    urls: List[str]
    evidence_hashes: List[str]
    notes: Optional[str] = None
    lookups: List[LookupResultItem] = []
    sent_at: Optional[str] = None
    deadline: Optional[str] = None
    due_at: Optional[str] = None
    seconds_remaining: Optional[float] = None
    created_at: str
    updated_at: str


class CandidateMatchItem(BaseModel):
    """A discovery candidate scraped/detected from reverse image search."""
    candidate_id: str
    page_url: str
    image_url: str
    domain: str
    match_type: str = "full"  # "full" | "partial" | "similar"
    verified: Optional[bool] = None  # True (Hamming <= 10 or SSCD >= 0.70) | False | None (user to confirm)
    distance: Optional[int] = None
    similarity: Optional[float] = Field(None, description="Neural SSCD cosine similarity in range [-1.0, 1.0]")
    sscd_verified: Optional[bool] = Field(None, description="True if SSCD similarity >= threshold")
    note: Optional[str] = None


class ScanResponse(BaseModel):
    """Response returned from POST /v1/scan."""
    original_id: str
    phash: str
    dhash: str
    sha256: str
    intimate: bool
    candidates: List[CandidateMatchItem]
    stop_ncii: Optional[Dict[str, Any]] = None
    daily_scans_remaining: int
    sscd_embedding: Optional[List[float]] = Field(None, description="576-dim L2-normalized SSCD vector")


class CaseCreateFromCandidatesRequest(BaseModel):
    """Create a case selecting candidate IDs from scan or manual URLs."""
    user_id: str
    original_id: Optional[str] = None
    candidate_ids: Optional[List[str]] = []
    manual_urls: Optional[List[str]] = []
    notes: Optional[str] = None
    is_minor: bool = False


class CaseCheckResultItem(BaseModel):
    """HTTP status check for a target URL."""
    url: str
    status_code: Optional[int] = None
    removed_assessment: str  # "likely_removed" | "inconclusive"
    checked_at: str
    note: str


class CaseCheckResponse(BaseModel):
    """Response from live URL status probe."""
    case_id: str
    results: List[CaseCheckResultItem]
    advice: str = "Automated probes (404/410) are indicative; user confirmation is required before closing case."


class DueJobItem(BaseModel):
    """Case where 24-hour SLA remediation deadline has expired."""
    case_id: str
    user_id: str
    due_at: str
    overdue_seconds: float


class DueJobsResponse(BaseModel):
    """Response for cron jobs checking expired cases."""
    count: int
    jobs: List[DueJobItem]

