import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.storage import storage
from app.sms import get_sms_dispatcher
from app.websocket_manager import ws_manager

logger = logging.getLogger("emergencysos.escalation")

# In-memory dictionary tracking running escalation asyncio Tasks: session_id -> asyncio.Task
_active_escalation_tasks: Dict[str, asyncio.Task] = {}


async def _run_escalation_timer(session_id: str, timeout_seconds: int):
    """Sleeps for timeout_seconds and triggers auto-escalation if not cancelled."""
    try:
        await asyncio.sleep(timeout_seconds)

        # Check session status in storage
        session = await storage.get_session(session_id)
        if not session:
            return

        if session.get("status") == "active":
            logger.warning(f"🚨 [AUTO-ESCALATION] 60s Timer Expired for Session '{session_id}'! Triggering Secondary Tier & Police Alert!")
            
            # Update session state
            await storage.update_session(session_id, {
                "status": "escalated",
                "auto_escalated": True,
                "escalated_at": datetime.now(timezone.utc).isoformat()
            })

            # Broadcast to guardians
            await ws_manager.broadcast_to_guardians(session_id, {
                "type": "escalation",
                "session_id": session_id,
                "message": "60-second timer expired without cancellation! Alert escalated to secondary tier & local PCR dispatch.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            # Dispatch secondary SMS
            contacts = session.get("contacts", [])
            tier2 = [c for c in contacts if c.get("priority", 1) >= 2] or contacts
            sms_client = get_sms_dispatcher()

            victim_name = session.get("user_name", "Victim")
            loc = session.get("current_location", {})
            tracking_url = session.get("tracking_url", "")

            esc_msg = (
                f"🚨 URGENT POLICE / GUARDIAN ESCALATION 🚨\n"
                f"{victim_name} triggered an SOS and did NOT cancel within 60s.\n"
                f"Last known coordinates: ({loc.get('lat')}, {loc.get('lng')})\n"
                f"Live Radar: {tracking_url}\n"
                f"Please alert Police Control Room (PCR 112) immediately."
            )

            for c in tier2:
                phone = c.get("phone")
                if phone:
                    await sms_client.send_sms(phone, esc_msg)

    except asyncio.CancelledError:
        logger.info(f"Escalation timer successfully disarmed for session '{session_id}'.")
    except Exception as e:
        logger.error(f"Error in escalation timer for '{session_id}': {e}")
    finally:
        _active_escalation_tasks.pop(session_id, None)


def schedule_escalation_timer(session_id: str, timeout_seconds: int = 60) -> asyncio.Task:
    """Schedule the 60-second auto-escalation task."""
    task = asyncio.create_task(_run_escalation_timer(session_id, timeout_seconds))
    _active_escalation_tasks[session_id] = task
    return task


def cancel_escalation_timer(session_id: str):
    """Cancel and disarm the pending escalation timer."""
    task = _active_escalation_tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()
        logger.info(f"Cancelled escalation timer task for session '{session_id}'.")
