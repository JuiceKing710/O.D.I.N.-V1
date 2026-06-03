from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import PermissionManager


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

