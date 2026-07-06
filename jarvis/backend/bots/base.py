from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import PermissionApprovalRequired, PermissionManager


@dataclass(slots=True)
class BotRequest:
    sender: str
    action: str
    payload: dict[str, Any]
    correlation_id: str


@dataclass(slots=True)
class BotResponse:
    ok: bool
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Bot(ABC):
    name: str
    description: str
    # Per-bot dispatch timeout; None uses BotManager's default. Bots whose
    # actions legitimately run long (shell commands, image generation, page
    # fetches) override this so the dispatch timeout matches the slowest
    # operation they can perform instead of killing it mid-flight.
    timeout_seconds: float | None = None
    # Whether a timed-out dispatch may be retried. A timeout cannot cancel the
    # worker thread the action runs on, so for side-effectful bots (shell
    # commands, desktop control, image generation, file writes) a retry would
    # run the action a second time while the first is still executing.
    retry_on_timeout: bool = True

    def __init__(self, permission_manager: PermissionManager, audit_logger: AuditLogger) -> None:
        self.permission_manager = permission_manager
        self.audit_logger = audit_logger

    @abstractmethod
    async def on_request(self, request: BotRequest) -> BotResponse:
        raise NotImplementedError

    def capabilities(self) -> list[str]:
        return []

    def get_persona(self) -> str:
        return self.description

    @staticmethod
    def permission_response(exc: PermissionError) -> BotResponse:
        payload = {}
        if isinstance(exc, PermissionApprovalRequired):
            payload["permission_request"] = exc.request.to_api()
        return BotResponse(ok=False, payload=payload, error=str(exc))

    def permission_metadata(self, request: BotRequest) -> dict[str, Any]:
        return {
            "bot": self.name,
            "action": request.action,
            "payload": request.payload,
            "sender": request.sender,
        }
