from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jarvis.backend.core.bot_manager import BotManager, BotMessage
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
    ) -> None:
        self.memory = memory
        self.bot_manager = bot_manager
        self.lm_provider = lm_provider
        self.audit_logger = audit_logger

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
        self.memory.add_message(convo.convo_id, "user", normalized)

        bot_name, bot_reply = await self._maybe_dispatch_bot(normalized)
        if bot_reply is not None:
            reply = bot_reply
        else:
            context = [
                item.content for item in self.memory.query_messages(user.user_id, normalized, limit=5)
            ]
            reply = await self.lm_provider.generate(normalized, context=context, metadata=metadata or {})

        self.memory.add_message(convo.convo_id, "assistant", reply)
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

    async def _maybe_dispatch_bot(self, message: str) -> tuple[str | None, str | None]:
        if not message.startswith("/"):
            return None, None
        parts = message[1:].split(maxsplit=2)
        if len(parts) < 2:
            return None, "Bot command format is /<bot_name> <action> [text]."
        bot_name, action = parts[0], parts[1]
        payload = {"text": parts[2] if len(parts) == 3 else ""}
        response = await self.bot_manager.dispatch(
            BotMessage(sender="user", recipient=bot_name, action=action, payload=payload)
        )
        if response is None:
            return bot_name, f"Unknown bot: {bot_name}"
        if not response.ok:
            return bot_name, response.error or "Bot request failed."
        text = response.payload.get("text")
        return bot_name, str(text) if text is not None else "Bot request completed."

