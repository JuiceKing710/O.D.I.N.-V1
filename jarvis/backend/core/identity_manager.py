from __future__ import annotations

from typing import Any

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.memory_manager import MemoryManager

# The fields a caller (UI, heartbeat) is allowed to change. Anything else in a
# patch is ignored so the identity store cannot accumulate arbitrary keys.
EDITABLE_KEYS = frozenset({"traits", "narrative", "mood", "interests"})


class IdentityManager:
    """Odin's persistent self-model (master spec §4 — Identity Persistence).

    Thin layer over :class:`MemoryManager`'s ``identity_state`` store: it
    validates updates, emits ``identity.updated`` events, and is the seam the
    heartbeat loop uses to evolve the narrative each tick. Defaults live in
    ``MemoryManager.DEFAULT_IDENTITY`` and are merged on read, so an unseeded
    install still has a coherent identity.
    """

    def __init__(self, memory: MemoryManager, event_bus: EventBus | None = None) -> None:
        self.memory = memory
        self.event_bus = event_bus

    def get(self) -> dict[str, Any]:
        return self.memory.get_identity()

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        cleaned = {key: value for key, value in patch.items() if key in EDITABLE_KEYS}
        if not cleaned:
            return self.get()
        identity = self.memory.update_identity(cleaned)
        if self.event_bus is not None:
            self.event_bus.publish("identity.updated", identity)
        return identity

    def set_narrative(self, narrative: str, mood: str | None = None) -> dict[str, Any]:
        """Used by the heartbeat to record 'what I'm doing now' each tick."""
        patch: dict[str, Any] = {"narrative": narrative}
        if mood is not None:
            patch["mood"] = mood
        return self.update(patch)

    def context(self) -> list[str]:
        return self.memory.identity_context()
