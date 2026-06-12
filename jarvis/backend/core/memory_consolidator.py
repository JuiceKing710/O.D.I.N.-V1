from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.lm_provider import LMProviderInterface
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.settings_store import SettingsStore

EXTRACT_PROMPT = (
    "You maintain long-term memory for a personal assistant. Review the "
    "conversation transcript below and extract durable facts worth remembering "
    "about the user: preferences, possessions, people, projects, and plans. "
    "Reply with one short fact per line (at most 8 lines). If there is nothing "
    "durable, reply with exactly: NOTHING\n\nTranscript:\n"
)

MERGE_PROMPT = (
    "You maintain a short profile of the user for a personal assistant. Merge "
    "the new facts into the existing profile: keep it under 900 characters, "
    "drop duplicates, resolve contradictions in favor of the new facts, and "
    "reply with only the revised profile text.\n\nExisting profile:\n{profile}\n\n"
    "New facts:\n{facts}"
)

LAST_RUN_KEY = "last_consolidation_at"


class MemoryConsolidator:
    """Sleep-time memory: distills recent conversations into durable memory
    documents and the always-in-context profile block."""

    def __init__(
        self,
        memory: MemoryManager,
        lm_provider: LMProviderInterface,
        settings: SettingsStore,
        event_bus: EventBus | None = None,
        *,
        hour: int = 4,
        enabled: bool = True,
    ) -> None:
        if hour not in range(24):
            raise ValueError("Consolidation hour must be between 0 and 23")
        self.memory = memory
        self.lm_provider = lm_provider
        self.settings = settings
        self.event_bus = event_bus
        self.hour = hour
        self.enabled = enabled
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def consolidate(self, username: str = "local-user") -> dict[str, Any]:
        user = self.memory.get_or_create_user(username)
        since = self._last_run_at() or (
            datetime.now(timezone.utc) - timedelta(hours=24)
        ).strftime("%Y-%m-%d %H:%M:%S")
        messages = self.memory.recent_messages(user.user_id, since_iso=since)
        if len(messages) < 2:
            return {"facts_saved": 0, "messages_reviewed": len(messages), "skipped": True}

        transcript = "\n".join(
            f"{record.role}: {record.content[:300]}" for record in messages[-80:]
        )
        raw_facts = await self.lm_provider.generate(EXTRACT_PROMPT + transcript, context=[])
        facts = []
        for line in raw_facts.splitlines():
            cleaned = line.strip().lstrip("-•*0123456789. ").strip()
            if cleaned and cleaned.upper() != "NOTHING" and len(cleaned) > 8:
                facts.append(cleaned)
        facts = facts[:8]

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for fact in facts:
            self.memory.save_document(
                user.user_id,
                document_id=f"memory-{stamp}-{uuid.uuid4().hex[:8]}",
                source=f"consolidated:{stamp}",
                content=fact,
            )

        profile_updated = False
        if facts:
            profile = self.memory.get_memory_blocks().get("human", "")
            merged = await self.lm_provider.generate(
                MERGE_PROMPT.format(profile=profile or "(empty)", facts="\n".join(facts)),
                context=[],
            )
            cleaned_profile = merged.strip()[:1200]
            if cleaned_profile:
                self.memory.update_memory_block("human", cleaned_profile)
                profile_updated = True

        self._record_run()
        result = {
            "facts_saved": len(facts),
            "messages_reviewed": len(messages),
            "profile_updated": profile_updated,
            "skipped": False,
        }
        if self.event_bus is not None:
            self.event_bus.publish("memory.consolidated", result)
        return result

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="jarvis-memory-consolidator")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            delay = self._seconds_until_next_run()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                return
            except TimeoutError:
                pass
            try:
                await self.consolidate()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - the nightly loop must survive
                self.last_error = str(exc)

    def _seconds_until_next_run(self) -> float:
        now = datetime.now().astimezone()
        target = now.replace(hour=self.hour, minute=30, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    def _last_run_at(self) -> str | None:
        value = self.settings.read().get(LAST_RUN_KEY)
        return str(value) if value else None

    def _record_run(self) -> None:
        self.settings.update(
            {LAST_RUN_KEY: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
        )
