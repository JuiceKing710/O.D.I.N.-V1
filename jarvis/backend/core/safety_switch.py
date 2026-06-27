from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.utils.audit_logging import AuditLogger

# Settings keys for the persisted halt state. Persisting to settings (rather than
# only in memory) means the stop survives a backend restart: if Odin is halted
# and the process is relaunched, it comes back halted until explicitly resumed.
ENGAGED_KEY = "emergency_stop"
AT_KEY = "emergency_stop_at"
REASON_KEY = "emergency_stop_reason"

# Bots whose actions touch the real world (files, shell, desktop, generated
# media on disk). These are refused while halted. Read-only analysis bots
# (research/code) are intentionally left running so Odin can still answer.
HIGH_IMPACT_BOTS = frozenset({"system", "file", "desktop", "image"})


class SafetySwitch:
    """Emergency stop / kill switch (master spec §Safety).

    A single, settings-backed boolean that, while engaged, blocks every
    high-impact bot action and pauses the heartbeat loop. It is deliberately
    simple and synchronous: any code path about to take a real-world action
    can cheaply ask :meth:`is_engaged` first.
    """

    def __init__(
        self,
        settings: SettingsStore,
        event_bus: EventBus | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.settings = settings
        self.event_bus = event_bus
        self.audit_logger = audit_logger

    def is_engaged(self) -> bool:
        try:
            return bool(self.settings.read().get(ENGAGED_KEY))
        except Exception:  # noqa: BLE001 - a settings read must never block a safety check
            # Fail safe: if we cannot determine the state, do not halt normal
            # operation on a transient read error.
            return False

    def engage(self, reason: str | None = None, actor: str = "user") -> dict[str, Any]:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cleaned = (reason or "").strip() or "manual emergency stop"
        self.settings.update(
            {ENGAGED_KEY: True, AT_KEY: stamp, REASON_KEY: cleaned}
        )
        if self.audit_logger is not None:
            self.audit_logger.log(
                actor=actor,
                action="safety:emergency_stop",
                result="engaged",
                metadata={"reason": cleaned},
            )
        if self.event_bus is not None:
            self.event_bus.publish("safety.emergency_stop", self.status())
        return self.status()

    def release(self, actor: str = "user") -> dict[str, Any]:
        self.settings.update({ENGAGED_KEY: False, REASON_KEY: None})
        if self.audit_logger is not None:
            self.audit_logger.log(
                actor=actor,
                action="safety:resume",
                result="released",
                metadata={},
            )
        if self.event_bus is not None:
            self.event_bus.publish("safety.released", self.status())
        return self.status()

    def status(self) -> dict[str, Any]:
        data = self.settings.read()
        engaged = bool(data.get(ENGAGED_KEY))
        return {
            "engaged": engaged,
            "since": data.get(AT_KEY) if engaged else None,
            "reason": data.get(REASON_KEY) if engaged else None,
            "blocked_bots": sorted(HIGH_IMPACT_BOTS) if engaged else [],
        }
