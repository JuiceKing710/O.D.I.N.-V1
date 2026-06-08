from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from jarvis.backend.core.bot_manager import BotManager, BotMessage
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.lm_provider import LMProviderInterface
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.utils.audit_logging import AuditLogger


class JarvisCore:
    def __init__(
        self,
        memory: MemoryManager,
        bot_manager: BotManager,
        lm_provider: LMProviderInterface,
        audit_logger: AuditLogger,
        event_bus: EventBus | None = None,
    ) -> None:
        self.memory = memory
        self.bot_manager = bot_manager
        self.lm_provider = lm_provider
        self.audit_logger = audit_logger
        self.event_bus = event_bus

    async def handle_message(
        self,
        message: str,
        username: str,
        conversation_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = message.strip()
        if not normalized:
            raise ValueError("Message cannot be empty")

        user = self.memory.get_or_create_user(username)
        convo = (
            self.memory.get_conversation(conversation_id, user.user_id)
            if conversation_id is not None
            else self.memory.create_conversation(user.user_id, title=normalized[:80])
        )
        user_message = self.memory.add_message(convo.convo_id, "user", normalized)
        self._publish_chat_message(user_message.role, user_message.content, convo.convo_id)

        bot_name, bot_reply = await self._maybe_dispatch_bot(normalized)
        if bot_reply is not None:
            reply = bot_reply
        else:
            context = self.memory.query_context(user.user_id, normalized, limit=5)
            reply = await self.lm_provider.generate(normalized, context=context, metadata=metadata or {})

        assistant_message = self.memory.add_message(convo.convo_id, "assistant", reply)
        self._publish_chat_message(assistant_message.role, assistant_message.content, convo.convo_id)
        self.audit_logger.log(
            actor=username,
            action="chat",
            result="ok",
            metadata={"conversation_id": convo.convo_id, "bot": bot_name},
        )
        return {
            "conversation_id": convo.convo_id,
            "reply": reply,
            "bot": bot_name,
            "created_at": datetime.now(timezone.utc),
        }

    def _publish_chat_message(self, role: str, content: str, conversation_id: int) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            "chat.message",
            {
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
            },
        )

    async def _maybe_dispatch_bot(self, message: str) -> tuple[str | None, str | None]:
        parsed = self._parse_bot_request(message)
        if parsed is None:
            return None, None
        bot_name, action, payload = parsed
        bot = self.bot_manager.get(bot_name)
        if bot is None or action not in bot.capabilities():
            return bot_name, f"Unsupported planned action: {bot_name}.{action}"
        response = await self.bot_manager.dispatch(
            BotMessage(sender="user", recipient=bot_name, action=action, payload=payload)
        )
        if response is None:
            return bot_name, f"Unknown bot: {bot_name}"
        if not response.ok:
            pending = response.payload.get("permission_request")
            if isinstance(pending, dict):
                reason = pending.get("reason") or f"{bot_name}.{action}"
                return bot_name, f"Approval required before Jarvis can continue: {reason}"
            return bot_name, response.error or "Bot request failed."
        text = response.payload.get("text")
        return bot_name, str(text) if text is not None else "Bot request completed."

    @staticmethod
    def _parse_bot_request(message: str) -> tuple[str, str, dict[str, Any]] | None:
        if message.startswith("/"):
            parts = message[1:].split(maxsplit=2)
            if len(parts) < 2:
                return None
            return parts[0], parts[1], {"text": parts[2] if len(parts) == 3 else ""}

        patterns = (
            (r"^(?:research|search the web for|look up)\s+(.+)$", "research", "search"),
            (r"^(?:analyze code|analyze file)\s+(.+)$", "code", "analyze"),
            (r"^(?:read file|open file)\s+(.+)$", "file", "read"),
            (r"^(?:run command|execute command)\s+(.+)$", "system", "execute"),
        )
        for pattern, bot, action in patterns:
            match = re.match(pattern, message.strip(), flags=re.IGNORECASE | re.DOTALL)
            if match:
                return bot, action, {"text": match.group(1).strip()}
        write_match = re.match(
            r"^write file\s+([^\n]+)\n(.+)$",
            message.strip(),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if write_match:
            return "file", "write", {
                "path": write_match.group(1).strip(),
                "content": write_match.group(2),
            }
        return None
