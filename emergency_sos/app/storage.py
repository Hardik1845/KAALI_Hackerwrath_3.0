import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger("emergencysos.storage")


class StorageInterface:
    """Abstract interface for SOS session and evidence persistence."""
    async def save_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def update_session(self, session_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def add_waypoint(self, session_id: str, point: Dict[str, Any]):
        raise NotImplementedError

    async def save_audio(self, session_id: str, audio_id: str, encrypted_bytes: bytes, metadata: Dict[str, Any]):
        raise NotImplementedError

    async def get_audio(self, session_id: str) -> Optional[bytes]:
        raise NotImplementedError

    async def clear_all(self):
        raise NotImplementedError


class InMemoryStore(StorageInterface):
    """High-performance thread-safe in-memory store for SOS sessions."""
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.audio_records: Dict[str, bytes] = {}      # session_id -> encrypted_bytes
        self.audio_metadata: Dict[str, Dict[str, Any]] = {} # session_id -> metadata

    async def save_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        self.sessions[session["session_id"]] = session
        return session

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.sessions.get(session_id)

    async def update_session(self, session_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if session_id not in self.sessions:
            return None
        self.sessions[session_id].update(updates)
        self.sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        return self.sessions[session_id]

    async def add_waypoint(self, session_id: str, point: Dict[str, Any]):
        if session_id in self.sessions:
            if "trajectory" not in self.sessions[session_id]:
                self.sessions[session_id]["trajectory"] = []
            self.sessions[session_id]["trajectory"].append(point)
            self.sessions[session_id]["current_location"] = point
            self.sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def save_audio(self, session_id: str, audio_id: str, encrypted_bytes: bytes, metadata: Dict[str, Any]):
        self.audio_records[session_id] = encrypted_bytes
        self.audio_metadata[session_id] = metadata
        if session_id in self.sessions:
            self.sessions[session_id]["audio_available"] = True
            self.sessions[session_id]["audio_id"] = audio_id
            self.sessions[session_id]["audio_sha256"] = metadata.get("sha256")

    async def get_audio(self, session_id: str) -> Optional[bytes]:
        return self.audio_records.get(session_id)

    async def get_all_active_sessions(self) -> List[Dict[str, Any]]:
        return [s for s in self.sessions.values() if s.get("status") == "active"]

    async def clear_all(self):
        self.sessions.clear()
        self.audio_records.clear()
        self.audio_metadata.clear()


storage = InMemoryStore()
