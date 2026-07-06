from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.safety_switch import HIGH_IMPACT_BOTS, SafetySwitch
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
        event_bus: EventBus | None = None,
        timeout_seconds: float = 10.0,
        retry_count: int = 1,
        acl: dict[str, set[str]] | None = None,
        safety_switch: SafetySwitch | None = None,
    ) -> None:
        self.permission_manager = permission_manager
        self.audit_logger = audit_logger
        self.event_bus = event_bus
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count
        self.acl = acl or {}
        self.safety_switch = safety_switch
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
        if message.recipient == "*":
            responses = await self.broadcast(message.sender, message.action, message.payload)
            return BotResponse(
                ok=True,
                payload={
                    name: {
                        "ok": response.ok,
                        "payload": response.payload,
                        "error": response.error,
                    }
                    for name, response in responses.items()
                },
            )
        bot = self._bots.get(message.recipient)
        if bot is None:
            return None
        if (
            self.safety_switch is not None
            and message.recipient in HIGH_IMPACT_BOTS
            and self.safety_switch.is_engaged()
        ):
            self.audit_logger.log(
                actor=message.sender,
                action=f"bot:{message.recipient}:{message.action}",
                result="halted",
                metadata={"correlation_id": message.correlation_id},
            )
            self._publish_status(message, "halted")
            return BotResponse(
                ok=False,
                error="Odin is halted (emergency stop engaged). Resume to allow this action.",
            )
        if not self._is_allowed(message.sender, message.recipient):
            self.audit_logger.log(
                actor=message.sender,
                action=f"bot:{message.recipient}:{message.action}",
                result="denied",
                metadata={"correlation_id": message.correlation_id},
            )
            self._publish_status(message, "denied")
            return BotResponse(ok=False, error="Bot communication denied by ACL")
        request = BotRequest(
            sender=message.sender,
            action=message.action,
            payload=message.payload,
            correlation_id=message.correlation_id,
        )
        self._publish_status(message, "acknowledged")
        timeout_seconds = (
            bot.timeout_seconds if bot.timeout_seconds is not None else self.timeout_seconds
        )
        attempts = (self.retry_count + 1) if bot.retry_on_timeout else 1
        for attempt in range(1, attempts + 1):
            try:
                response = await asyncio.wait_for(bot.on_request(request), timeout_seconds)
                self.audit_logger.log(
                    actor=message.sender,
                    action=f"bot:{message.recipient}:{message.action}",
                    result="ok" if response.ok else "error",
                    metadata={
                        "correlation_id": message.correlation_id,
                        "attempt": attempt,
                    },
                )
                self._publish_status(message, "completed" if response.ok else "error")
                return response
            except TimeoutError:
                self.audit_logger.log(
                    actor=message.sender,
                    action=f"bot:{message.recipient}:{message.action}",
                    result="timeout",
                    metadata={
                        "correlation_id": message.correlation_id,
                        "attempt": attempt,
                    },
                )
                self._publish_status(message, "timeout")
        return BotResponse(ok=False, error="Bot request timed out")

    async def broadcast(self, sender: str, action: str, payload: dict[str, Any]) -> dict[str, BotResponse]:
        responses: dict[str, BotResponse] = {}
        for name in self.names():
            if not self._is_allowed(sender, name):
                continue
            message = BotMessage(sender=sender, recipient=name, action=action, payload=payload)
            response = await self.dispatch(message)
            if response is not None:
                responses[name] = response
        return responses

    def _is_allowed(self, sender: str, recipient: str) -> bool:
        allowed = self.acl.get(sender) or self.acl.get("*")
        if allowed is None:
            return True
        return recipient in allowed or "*" in allowed

    def _publish_status(self, message: BotMessage, status: str) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            "bot.status",
            {
                "sender": message.sender,
                "recipient": message.recipient,
                "action": message.action,
                "status": status,
                "correlation_id": message.correlation_id,
            },
        )
