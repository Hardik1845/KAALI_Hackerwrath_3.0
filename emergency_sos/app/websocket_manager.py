import json
import logging
from typing import Dict, List, Any
from fastapi import WebSocket

logger = logging.getLogger("emergencysos.websocket")


class ConnectionManager:
    """
    Manages active WebSocket streams for victims and guardians.
    Maintains fan-out pub/sub routing per session_id.
    """
    def __init__(self):
        # session_id -> List[WebSocket] (guardians watching)
        self.guardian_connections: Dict[str, List[WebSocket]] = {}
        # session_id -> WebSocket (victim streaming)
        self.victim_connections: Dict[str, WebSocket] = {}

    async def connect_victim(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.victim_connections[session_id] = websocket
        logger.info(f"Victim WebSocket connected for session '{session_id}'")

    def disconnect_victim(self, session_id: str):
        if session_id in self.victim_connections:
            del self.victim_connections[session_id]
            logger.info(f"Victim WebSocket disconnected for session '{session_id}'")

    async def connect_guardian(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        if session_id not in self.guardian_connections:
            self.guardian_connections[session_id] = []
        self.guardian_connections[session_id].append(websocket)
        logger.info(f"Guardian connected to session '{session_id}' (Total: {len(self.guardian_connections[session_id])})")

    def disconnect_guardian(self, session_id: str, websocket: WebSocket):
        if session_id in self.guardian_connections:
            if websocket in self.guardian_connections[session_id]:
                self.guardian_connections[session_id].remove(websocket)
            if not self.guardian_connections[session_id]:
                del self.guardian_connections[session_id]
        logger.info(f"Guardian disconnected from session '{session_id}'")

    async def broadcast_to_guardians(self, session_id: str, message: Dict[str, Any]):
        """Broadcasts a live GPS location beacon or status update to all connected guardians."""
        guardians = self.guardian_connections.get(session_id, [])
        if not guardians:
            return

        dead_connections = []
        payload = json.dumps(message)

        for ws in guardians:
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to guardian ws ({e}); queueing removal.")
                dead_connections.append(ws)

        for dead in dead_connections:
            if dead in guardians:
                guardians.remove(dead)


ws_manager = ConnectionManager()
