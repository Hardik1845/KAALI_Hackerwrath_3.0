from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class LocationPoint(BaseModel):
    """GPS coordinate and kinetic metrics."""
    lat: float = Field(..., description="Latitude")
    lng: float = Field(..., description="Longitude")
    accuracy: Optional[float] = Field(None, description="Accuracy radius in meters")
    speed: Optional[float] = Field(None, description="Ground speed in m/s")
    timestamp: Optional[str] = Field(None, description="ISO8601 timestamp")


class EmergencyContact(BaseModel):
    """Emergency contact recipient for SMS and voice alerts."""
    name: str = Field(..., description="Contact name")
    phone: str = Field(..., description="E.164 phone number, e.g. +919876543210")
    relation: str = Field("Family", description="Relation to victim (e.g. Mother, Sister, Friend)")
    priority: int = Field(1, description="Notification priority tier (1 = Immediate, 2 = Escalation)")


class SafeHavenItem(BaseModel):
    """Nearby safe haven located within emergency perimeter."""
    name: str
    type: str  # "police", "pharmacy", "hospital", "metro"
    lat: float
    lng: float
    distance_m: int
    open_24h: bool = True
    contact_phone: Optional[str] = None


class SOSTriggerRequest(BaseModel):
    """Payload to trigger immediate emergency alert."""
    user_id: str = Field(..., description="Victim unique user ID")
    user_name: str = Field("User", description="Victim display name")
    location: LocationPoint = Field(..., description="Current GPS fix at trigger moment")
    trigger_type: str = Field("manual", description="'manual' | 'voice' | 'triple_tap'")
    contacts: List[EmergencyContact] = Field(default_factory=list, description="Registered emergency contacts")
    passphrase: Optional[str] = Field(None, description="Custom cancellation secret passphrase")


class SOSTriggerResponse(BaseModel):
    """Response returned upon immediate SOS broadcast initiation."""
    session_id: str
    status: str = "active"
    tracking_url: str
    sms_sent_to: List[str]
    calls_placed_to: List[str] = []
    triggered_at: str
    auto_escalation_at: str
    seconds_to_escalate: int
    nearest_havens: List[SafeHavenItem]


class LocationUpdateRequest(BaseModel):
    """Periodic GPS stream beacon from client."""
    lat: float
    lng: float
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    timestamp: Optional[str] = None


class SOSCancelRequest(BaseModel):
    """Request to disarm active SOS session."""
    session_id: str
    passphrase: str = Field(..., description="Secret passphrase to confirm identity")


class SOSCancelResponse(BaseModel):
    """Response confirming session de-escalation or duress flag."""
    session_id: str
    status: str  # "cancelled" or "duress"
    cancelled_at: str
    duration_seconds: float
    is_duress: bool = False
    message: str


class GuardianSessionView(BaseModel):
    """Complete situational awareness snapshot for guardians monitoring live link."""
    session_id: str
    user_name: str
    status: str  # "active" | "cancelled" | "escalated"
    triggered_at: str
    current_location: LocationPoint
    trajectory: List[LocationPoint]
    audio_available: bool = False
    audio_url: Optional[str] = None
    auto_escalated: bool = False
    nearest_havens: List[SafeHavenItem] = []
    emergency_contacts: List[EmergencyContact] = []


class AudioUploadResponse(BaseModel):
    """Metadata returned after ambient audio chunk upload."""
    session_id: str
    audio_id: str
    encrypted: bool = True
    sha256_hash: str
    uploaded_at: str
    size_bytes: int


class IncidentDossierResponse(BaseModel):
    """Forensic court-admissible PDF incident report."""
    session_id: str
    user_name: str
    pdf_base64: str
    incident_sha256: str
    total_waypoints: int
    audio_included: bool
    generated_at: str
