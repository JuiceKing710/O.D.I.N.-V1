from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import PermissionManager


@dataclass(slots=True)
class BotMessage:
    sender: str
    recipient: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    reply_to: str | None = None


class BotManager:
    def __init__(
        self,
        permission_manager: PermissionManager,
        audit_logger: AuditLogger,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.permission_manager = permission_manager
        self.audit_logger = audit_logger
        self.timeout_seconds = timeout_seconds
        self._bots: dict[str, Bot] = {}

    def register(self, bot: Bot) -> None:
        if bot.name in self._bots:
            raise ValueError(f"Bot already registered: {bot.name}")
        self._bots[bot.name] = bot

    def names(self) -> list[str]:
        return sorted(self._bots)

    def get(self, name: str) -> Bot | None:
        return self._bots.get(name)

    async def dispatch(self, message: BotMessage) -> BotResponse | None:
        bot = self._bots.get(message.recipient)
        if bot is None:
            return None
        request = BotRequest(
            sender=message.sender,
            action=message.action,
            payload=message.payload,
            correlation_id=message.correlation_id,
        )
        try:
            response = await asyncio.wait_for(bot.on_request(request), self.timeout_seconds)
            self.audit_logger.log(
                actor=message.sender,
                action=f"bot:{message.recipient}:{message.action}",
                result="ok" if response.ok else "error",
                metadata={"correlation_id": message.correlation_id},
            )
            return response
        except TimeoutError:
            self.audit_logger.log(
                actor=message.sender,
                action=f"bot:{message.recipient}:{message.action}",
                result="timeout",
                metadata={"correlation_id": message.correlation_id},
            )
            return BotResponse(ok=False, error="Bot request timed out")

    async def broadcast(self, sender: str, action: str, payload: dict[str, Any]) -> dict[str, BotResponse]:
        responses: dict[str, BotResponse] = {}
        for name in self.names():
            message = BotMessage(sender=sender, recipient=name, action=action, payload=payload)
            response = await self.dispatch(message)
            if response is not None:
                responses[name] = response
        return responses

