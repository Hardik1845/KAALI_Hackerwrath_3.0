import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    HTTPException,
    status,
    Depends,
    Response
)
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os

from app.config import settings
from app.models import (
    SOSTriggerRequest,
    SOSTriggerResponse,
    SOSCancelRequest,
    SOSCancelResponse,
    LocationUpdateRequest,
    GuardianSessionView,
    AudioUploadResponse,
    IncidentDossierResponse,
    SafeHavenItem
)
from app.storage import storage
from app.sms import get_sms_dispatcher
from app.voice import get_voice_dispatcher
from app.havens import find_nearest_safe_havens
from app.security import (
    encrypt_audio_bytes,
    decrypt_audio_bytes,
    verify_cancel_passphrase,
    verify_api_key
)
from app.websocket_manager import ws_manager
from app.escalation import schedule_escalation_timer, cancel_escalation_timer
from app.dossier import compile_incident_dossier

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("emergencysos.main")

app = FastAPI(
    title="KAALI Emergency SOS Microservice",
    description="Mission-critical Real-Time SOS Dispatch, Encrypted Audio Witness & Forensic Evidence Service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files path for Guardian Dashboard
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health", tags=["System"])
async def health_check():
    """Liveness probe and system status check."""
    active_sessions = await storage.get_all_active_sessions()
    return {
        "status": "ok",
        "service": "kaali-emergency-sos",
        "version": "1.0.0",
        "active_sos_count": len(active_sessions),
        "sms_provider": settings.SMS_PROVIDER,
        "escalation_timeout_sec": settings.ESCALATION_TIMEOUT_SECONDS
    }


# =====================================================================
# EMERGENCY SOS REST ENDPOINTS
# =====================================================================

@app.post("/api/v1/sos/trigger", response_model=SOSTriggerResponse, tags=["SOS Core"])
async def trigger_sos(
    payload: SOSTriggerRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Trigger emergency SOS broadcast:
    1. Generates unique session tracking ID.
    2. Identifies nearest safe havens (Police, Pharmacies, Hospitals).
    3. Broadcasts immediate Tier 1 SMS alert with live radar link to emergency contacts.
    4. Initializes encrypted session storage with initial GPS waypoint.
    5. Starts 60-second auto-escalation timer for PCR / police dispatch.
    """
    session_id = f"sos_{uuid.uuid4().hex[:12]}"
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()
    escalate_at = (now_utc + timedelta(seconds=settings.ESCALATION_TIMEOUT_SECONDS)).isoformat()
    tracking_url = f"{settings.BASE_URL}/live/{session_id}"

    # 1. Spatial Safe Haven Lookup
    havens = find_nearest_safe_havens(payload.location.lat, payload.location.lng, limit=5)
    havens_data = [h.model_dump() for h in havens]

    # 2. SMS Broadcast to Registered Contacts
    contacts_data = [c.model_dump() for c in payload.contacts]
    sms_client = get_sms_dispatcher()
    sms_sent_to = await sms_client.broadcast_sos(
        contacts=contacts_data,
        victim_name=payload.user_name,
        location=payload.location.model_dump(),
        tracking_url=tracking_url
    )

    # 3. Voice Call Dispatch to Registered Contacts
    voice_client = get_voice_dispatcher()
    calls_placed_to = await voice_client.broadcast_voice_alerts(
        contacts=contacts_data,
        victim_name=payload.user_name,
        location=payload.location.model_dump()
    )

    # 4. Initialize Persistent Session Record
    initial_point = payload.location.model_dump()
    initial_point["timestamp"] = initial_point.get("timestamp") or now_iso

    session_record = {
        "session_id": session_id,
        "user_id": payload.user_id,
        "user_name": payload.user_name,
        "status": "active",
        "trigger_type": payload.trigger_type,
        "passphrase": payload.passphrase or settings.DEFAULT_CANCEL_PASSPHRASE,
        "triggered_at": now_iso,
        "auto_escalation_at": escalate_at,
        "auto_escalated": False,
        "tracking_url": tracking_url,
        "current_location": initial_point,
        "trajectory": [initial_point],
        "contacts": contacts_data,
        "sms_sent_to": sms_sent_to,
        "calls_placed_to": calls_placed_to,
        "nearest_havens": havens_data,
        "audio_available": False,
        "audio_id": None,
        "audio_sha256": None,
        "created_at": now_iso,
        "updated_at": now_iso
    }

    await storage.save_session(session_record)

    # 5. Schedule 60-second Auto-Escalation Timer
    schedule_escalation_timer(session_id, settings.ESCALATION_TIMEOUT_SECONDS)

    logger.info(f"🚨 SOS ACTIVATED: session={session_id}, user={payload.user_name}, SMS dispatched to {len(sms_sent_to)}, Voice Calls placed to {len(calls_placed_to)}.")

    return SOSTriggerResponse(
        session_id=session_id,
        status="active",
        tracking_url=tracking_url,
        sms_sent_to=sms_sent_to,
        calls_placed_to=calls_placed_to,
        triggered_at=now_iso,
        auto_escalation_at=escalate_at,
        seconds_to_escalate=settings.ESCALATION_TIMEOUT_SECONDS,
        nearest_havens=havens
    )


@app.post("/api/v1/sos/cancel", response_model=SOSCancelResponse, tags=["SOS Core"])
async def cancel_sos(
    payload: SOSCancelRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Cancel active SOS session using secret passphrase.
    Includes Coercion / Duress Detection:
    - If forced to cancel under threat, entering 'help' or 'danger' simulates
      cancellation to attacker while silently triggering immediate Police PCR dispatch.
    """
    session = await storage.get_session(payload.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SOS Session '{payload.session_id}' not found."
        )

    is_valid, is_duress = verify_cancel_passphrase(
        provided=payload.passphrase,
        actual=session.get("passphrase")
    )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect cancellation passphrase."
        )

    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()
    triggered_at_dt = datetime.fromisoformat(session["triggered_at"])
    duration = (now_utc - triggered_at_dt).total_seconds()

    if is_duress:
        # SILENT DURESS TRIGGERED: Do NOT disarm escalation! Secretly escalate!
        logger.warning(f"⚠️ [SILENT DURESS DETECTED] Session '{payload.session_id}' entered secret duress word! Escalating silently!")
        await storage.update_session(payload.session_id, {
            "status": "duress_escalated",
            "is_duress": True,
            "duress_triggered_at": now_iso
        })

        # Covertly broadcast duress alert to guardians
        await ws_manager.broadcast_to_guardians(payload.session_id, {
            "type": "duress_alert",
            "session_id": payload.session_id,
            "message": "CRITICAL: Silent Duress Passphrase entered! Victim coerced into canceling! Police alerted!",
            "timestamp": now_iso
        })

        # Return deceptive success so perpetrator sees "SOS Cancelled"
        return SOSCancelResponse(
            session_id=payload.session_id,
            status="cancelled",
            cancelled_at=now_iso,
            duration_seconds=duration,
            is_duress=True,
            message="SOS Deactivated successfully."
        )

    # NORMAL DISARM: Cancel escalation timer and update state
    cancel_escalation_timer(payload.session_id)
    await storage.update_session(payload.session_id, {
        "status": "cancelled",
        "cancelled_at": now_iso,
        "duration_seconds": duration,
        "is_duress": False
    })

    # Broadcast disarm to guardians
    await ws_manager.broadcast_to_guardians(payload.session_id, {
        "type": "cancelled",
        "session_id": payload.session_id,
        "message": f"SOS Cancelled by user ({duration:.1f}s after trigger). Safe.",
        "timestamp": now_iso
    })

    logger.info(f"SOS Disarmed normally: session={payload.session_id}, duration={duration:.1f}s")

    return SOSCancelResponse(
        session_id=payload.session_id,
        status="cancelled",
        cancelled_at=now_iso,
        duration_seconds=duration,
        is_duress=False,
        message="SOS Disarmed and cancelled successfully."
    )


@app.post("/api/v1/sos/{session_id}/audio", response_model=AudioUploadResponse, tags=["Audio Witness"])
async def upload_ambient_audio(
    session_id: str,
    file: UploadFile = File(...),
    api_key: str = Depends(verify_api_key)
):
    """
    Upload and immediately encrypt ambient audio clip captured during emergency.
    Audio is encrypted with AES-256 (Fernet) before touching disk or persistent storage.
    A SHA-256 cryptographic seal is generated for Section 65B forensic admissibility.
    """
    session = await storage.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SOS Session '{session_id}' not found."
        )

    raw_data = await file.read()
    if not raw_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty audio payload received."
        )

    max_bytes = settings.MAX_AUDIO_SIZE_MB * 1024 * 1024
    if len(raw_data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Audio file exceeds maximum size limit of {settings.MAX_AUDIO_SIZE_MB}MB."
        )

    # Encrypt raw audio with AES-256
    encrypted_bytes, sha256_hash = encrypt_audio_bytes(raw_data)
    audio_id = f"aud_{uuid.uuid4().hex[:10]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    metadata = {
        "audio_id": audio_id,
        "sha256": sha256_hash,
        "content_type": file.content_type or "audio/wav",
        "size_bytes": len(raw_data),
        "uploaded_at": now_iso
    }

    await storage.save_audio(session_id, audio_id, encrypted_bytes, metadata)

    # Notify watching guardians that ambient audio is available
    await ws_manager.broadcast_to_guardians(session_id, {
        "type": "audio_ready",
        "session_id": session_id,
        "audio_id": audio_id,
        "sha256": sha256_hash,
        "timestamp": now_iso
    })

    logger.info(f"Ambient audio saved: session={session_id}, id={audio_id}, sha256={sha256_hash[:16]}...")

    return AudioUploadResponse(
        session_id=session_id,
        audio_id=audio_id,
        encrypted=True,
        sha256_hash=sha256_hash,
        uploaded_at=now_iso,
        size_bytes=len(raw_data)
    )


@app.get("/api/v1/sos/{session_id}/audio", tags=["Audio Witness"])
async def stream_decrypted_audio(session_id: str):
    """
    Decrypts and serves the ambient audio witness recording for guardian playback.
    """
    session = await storage.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SOS Session '{session_id}' not found."
        )

    encrypted_bytes = await storage.get_audio(session_id)
    if not encrypted_bytes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audio recording found for session '{session_id}'."
        )

    try:
        decrypted = decrypt_audio_bytes(encrypted_bytes)
    except Exception as e:
        logger.error(f"Failed to decrypt audio for session '{session_id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt audio data."
        )

    meta = storage.audio_metadata.get(session_id, {})
    media_type = meta.get("content_type", "audio/wav")

    return Response(
        content=decrypted,
        media_type=media_type,
        headers={
            "Content-Disposition": f"inline; filename=ambient_{session_id}.wav",
            "X-Audio-SHA256": meta.get("sha256", "")
        }
    )


@app.get("/api/v1/sos/{session_id}", response_model=GuardianSessionView, tags=["Guardian View"])
async def get_guardian_session_snapshot(session_id: str):
    """
    Returns complete situational awareness state for the guardian live radar interface.
    """
    session = await storage.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SOS Session '{session_id}' not found."
        )

    audio_url = f"{settings.BASE_URL}/api/v1/sos/{session_id}/audio" if session.get("audio_available") else None

    return GuardianSessionView(
        session_id=session["session_id"],
        user_name=session.get("user_name", "Anonymous"),
        status=session.get("status", "active"),
        triggered_at=session.get("triggered_at", ""),
        current_location=session.get("current_location", {}),
        trajectory=session.get("trajectory", []),
        audio_available=session.get("audio_available", False),
        audio_url=audio_url,
        auto_escalated=session.get("auto_escalated", False),
        nearest_havens=session.get("nearest_havens", []),
        emergency_contacts=session.get("contacts", [])
    )


@app.get("/api/v1/sos/{session_id}/dossier", response_model=IncidentDossierResponse, tags=["Forensic Dossier"])
async def get_incident_dossier(session_id: str):
    """
    Generates a digitally sealed court-admissible PDF forensic incident report
    compliant with Section 65B of the Indian Evidence Act / BSA.
    """
    session = await storage.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SOS Session '{session_id}' not found."
        )

    return compile_incident_dossier(session)


# =====================================================================
# REAL-TIME WEBSOCKET STREAMS
# =====================================================================

@app.websocket("/ws/sos/{session_id}")
async def websocket_victim_stream(websocket: WebSocket, session_id: str):
    """
    Continuous real-time GPS beacon stream from the victim's mobile client.
    Receives periodic lat/lng updates, persists them in trajectory,
    and fans out live telemetry to all connected guardians.
    """
    await ws_manager.connect_victim(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # data: { "lat": float, "lng": float, "accuracy": float, "speed": float, "timestamp": str }
            if "lat" in data and "lng" in data:
                now_iso = datetime.now(timezone.utc).isoformat()
                waypoint = {
                    "lat": float(data["lat"]),
                    "lng": float(data["lng"]),
                    "accuracy": data.get("accuracy", 5.0),
                    "speed": data.get("speed", 0.0),
                    "timestamp": data.get("timestamp") or now_iso
                }
                # Persist to session
                await storage.add_waypoint(session_id, waypoint)

                # Fan-out broadcast to guardians
                await ws_manager.broadcast_to_guardians(session_id, {
                    "type": "location_update",
                    "session_id": session_id,
                    "location": waypoint,
                    "timestamp": now_iso
                })
    except WebSocketDisconnect:
        logger.info(f"Victim client disconnected from session '{session_id}'")
    except Exception as e:
        logger.warning(f"Error in victim ws for session '{session_id}': {e}")
    finally:
        ws_manager.disconnect_victim(session_id)


@app.websocket("/ws/guardian/{session_id}")
async def websocket_guardian_stream(websocket: WebSocket, session_id: str):
    """
    Subscribes a guardian's live radar dashboard to real-time telemetry updates.
    Fans out live GPS breadcrumbs, ambient audio notifications, and auto-escalation triggers.
    """
    await ws_manager.connect_guardian(session_id, websocket)
    try:
        # Send initial snapshot upon connection
        session = await storage.get_session(session_id)
        if session:
            await websocket.send_json({
                "type": "init_state",
                "session_id": session_id,
                "user_name": session.get("user_name"),
                "status": session.get("status"),
                "current_location": session.get("current_location"),
                "trajectory": session.get("trajectory", []),
                "audio_available": session.get("audio_available", False),
                "auto_escalated": session.get("auto_escalated", False),
                "nearest_havens": session.get("nearest_havens", []),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        # Keep alive and handle guardian ping/ack
        while True:
            text = await websocket.receive_text()
            if text == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info(f"Guardian disconnected from session '{session_id}'")
    except Exception as e:
        logger.warning(f"Error in guardian ws for session '{session_id}': {e}")
    finally:
        ws_manager.disconnect_guardian(session_id, websocket)


# =====================================================================
# GUARDIAN LIVE RADAR DASHBOARD (HTML / Leaflet UI)
# =====================================================================

@app.get("/live/{session_id}", response_class=HTMLResponse, tags=["Guardian UI"])
async def serve_live_dashboard(session_id: str):
    """
    Renders the interactive real-time Guardian Radar Dashboard.
    Features: Leaflet.js live map, live path breadcrumbs, Safe Havens overlay,
    encrypted ambient audio player, and instant emergency calling.
    """
    html_path = os.path.join(STATIC_DIR, "live.html")
    if os.path.isfile(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Inject session ID directly into template
            content = content.replace("{{SESSION_ID}}", session_id)
            return HTMLResponse(content=content)

    return HTMLResponse(content=f"<h1>KAALI Live Radar - Session {session_id}</h1><p>UI loading...</p>")
