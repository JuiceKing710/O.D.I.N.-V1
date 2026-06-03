from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from jarvis.backend.core.lm_provider import LMProviderInterface
from jarvis.backend.core.memory_manager import MemoryManager


@dataclass(slots=True)
class ReflectionSummary:
    conversation_id: int
    summary: str
    created_at: datetime


class ReflectionEngine:
    def __init__(self, memory: MemoryManager, lm_provider: LMProviderInterface) -> None:
        self.memory = memory
        self.lm_provider = lm_provider

    async def summarize_conversation(self, user_id: int, conversation_id: int) -> ReflectionSummary:
        messages = self.memory.query_messages(user_id, "", limit=50)
        contents = [message.content for message in messages if message.convo_id == conversation_id]
        if not contents:
            summary = "No conversation content available."
        else:
            summary = await self.lm_provider.generate(
                "Summarize this conversation for long-term memory.",
                context=contents,
                metadata={"task": "reflection"},
            )
        return ReflectionSummary(
            conversation_id=conversation_id,
            summary=summary,
            created_at=datetime.now(timezone.utc),
        )

