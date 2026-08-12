from collections import defaultdict
from datetime import datetime

class SessionManager:
    def __init__(self):
        self._sessions: dict[str, list] = defaultdict(list)
        self._pending_confirm: dict[str, dict] = {}  # session_id -> pending action
        self._last_entity: dict[str, dict] = {}  # session_id -> {"kategori": str, "id": str}

    def get_history(self, session_id: str) -> list:
        return self._sessions[session_id]

    def add_message(self, session_id: str, role: str, content: str):
        self._sessions[session_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

    def clear(self, session_id: str):
        self._sessions[session_id] = []
        self._pending_confirm.pop(session_id, None)
        self._last_entity.pop(session_id, None)

    def set_pending_confirm(self, session_id: str, action: dict):
        """Simpan action yang menunggu konfirmasi user."""
        self._pending_confirm[session_id] = action

    def get_pending_confirm(self, session_id: str) -> dict | None:
        return self._pending_confirm.get(session_id)

    def clear_pending_confirm(self, session_id: str):
        self._pending_confirm.pop(session_id, None)

    def set_last_entity(self, session_id: str, kategori: str, entity_id: str):
        """Catat entitas (finance/arsip/mom/jadwal) yang terakhir dibuat/diubah
        di session ini, supaya referensi seperti "tadi"/"yang baru" bisa
        diselesaikan ke ID yang tepat tanpa user harus sebut ID eksplisit."""
        self._last_entity[session_id] = {"kategori": kategori, "id": entity_id}

    def get_last_entity(self, session_id: str, kategori: str | None = None) -> dict | None:
        entity = self._last_entity.get(session_id)
        if entity and kategori and entity.get("kategori") != kategori:
            return None
        return entity

    def list_sessions(self) -> list:
        return list(self._sessions.keys())
