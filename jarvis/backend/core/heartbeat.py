from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.identity_manager import IdentityManager
from jarvis.backend.core.improvement_manager import ImprovementManager
from jarvis.backend.core.lm_provider import LMProviderInterface
from jarvis.backend.core.memory_consolidator import MemoryConsolidator
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.safety_switch import SafetySwitch
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.utils.reflection import ReflectionEngine

TICK_COUNT_KEY = "heartbeat_tick_count"
LAST_TICK_KEY = "heartbeat_last_tick_at"

CURIOSITY_PROMPT = (
    "You are Odin, a personal assistant reflecting between tasks. In one short "
    "sentence, name a single thing you are curious about or would like to learn "
    "to better help this user. Reply with just the one sentence."
)


class HeartbeatEngine:
    """Continuity engine (master spec §3).

    A single periodic loop that gives Odin ongoing internal continuity instead
    of stateless turns. Each tick: snapshot state, consolidate memory, reflect
    on a recent conversation, check goal alignment, generate a curiosity, update
    the identity narrative ("what I'm doing now"), and re-seal (persist + emit).

    The deterministic spine (snapshot → identity narrative → tick count → event)
    always runs; the LLM-backed steps are best-effort and never abort a tick.
    The whole tick is skipped while the emergency stop is engaged.
    """

    def __init__(
        self,
        memory: MemoryManager,
        lm_provider: LMProviderInterface,
        identity: IdentityManager,
        consolidator: MemoryConsolidator,
        settings: SettingsStore,
        safety_switch: SafetySwitch | None = None,
        event_bus: EventBus | None = None,
        improvement: ImprovementManager | None = None,
        *,
        interval_seconds: float = 1800.0,
        enabled: bool = True,
        username: str = "local-user",
        propose_every: int = 0,
    ) -> None:
        self.memory = memory
        self.lm_provider = lm_provider
        self.identity = identity
        self.consolidator = consolidator
        self.settings = settings
        self.safety_switch = safety_switch
        self.event_bus = event_bus
        self.improvement = improvement
        self.interval_seconds = max(interval_seconds, 1.0)
        self.enabled = enabled
        self.username = username
        # How often (in ticks) Odin surfaces a self-improvement proposal. 0
        # disables it. Proposals are always created as `pending` — never applied
        # without explicit human approval (master spec §8).
        self.propose_every = max(propose_every, 0)
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def tick(self) -> dict[str, Any]:
        if self.safety_switch is not None and self.safety_switch.is_engaged():
            payload = {"skipped": True, "reason": "emergency_stop"}
            self._publish("heartbeat.skipped", payload)
            return payload

        user = self.memory.get_or_create_user(self.username)
        conversations = self.memory.list_conversations(user.user_id, limit=100)
        active_goals = self.memory.list_goals(user.user_id, status="active")

        consolidated = await self._safe(self._consolidate())
        reflected = await self._safe(self._reflect(user.user_id, conversations))
        alignment = await self._safe(self._check_goal_alignment(active_goals))
        curiosity = await self._safe(self._generate_curiosity(user.user_id))

        tick_count = self._next_tick_count()
        proposal = await self._safe(self._maybe_propose(tick_count))
        narrative = (
            f"On heartbeat {tick_count}: tending {len(active_goals)} active goal(s) "
            f"across {len(conversations)} conversation(s) in memory."
        )
        self.identity.set_narrative(narrative)

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.settings.update({TICK_COUNT_KEY: tick_count, LAST_TICK_KEY: stamp})

        snapshot = {
            "skipped": False,
            "tick": tick_count,
            "at": stamp,
            "conversations": len(conversations),
            "active_goals": len(active_goals),
            "narrative": narrative,
            "consolidated": consolidated or {},
            "reflected_conversation": reflected,
            "goal_alignment": alignment,
            "curiosity": curiosity,
            "improvement_proposal": proposal,
        }
        self._publish("heartbeat.tick", snapshot)
        return snapshot

    def status(self) -> dict[str, Any]:
        data = self.settings.read()
        return {
            "enabled": self.enabled,
            "running": self._task is not None and not self._task.done(),
            "interval_seconds": self.interval_seconds,
            "tick_count": int(data.get(TICK_COUNT_KEY, 0) or 0),
            "last_tick_at": data.get(LAST_TICK_KEY),
            "last_error": self.last_error,
            "halted": bool(self.safety_switch is not None and self.safety_switch.is_engaged()),
        }

    # --- tick sub-steps (best-effort) -------------------------------------

    async def _consolidate(self) -> dict[str, Any]:
        return await self.consolidator.consolidate(self.username)

    async def _reflect(self, user_id: int, conversations: list) -> int | None:
        """Reflect on the most recent conversation that has no summary yet."""
        for convo in conversations:
            if convo.message_count <= 0:
                continue
            if self.memory.list_reflection_summaries(convo.convo_id):
                continue
            engine = ReflectionEngine(self.memory, self.lm_provider)
            await engine.summarize_conversation(user_id, convo.convo_id)
            return convo.convo_id
        return None

    async def _check_goal_alignment(self, goals: list) -> str | None:
        if not goals:
            return None
        listing = "\n".join(f"- {goal.text}" for goal in goals)
        verdict = await self.lm_provider.generate(
            "These are the user's active goals. In one short sentence, note "
            "whether recent activity still aligns with them or has drifted.\n\n"
            f"{listing}",
            context=[],
            metadata={"task": "goal_alignment"},
        )
        return verdict.strip() or None

    async def _generate_curiosity(self, user_id: int) -> str | None:
        raw = await self.lm_provider.generate(
            CURIOSITY_PROMPT, context=[], metadata={"task": "curiosity"}
        )
        interest = next((line.strip() for line in raw.splitlines() if line.strip()), "")
        if not interest:
            return None
        self.memory.save_document(
            user_id,
            document_id=f"curiosity-{uuid.uuid4().hex[:12]}",
            source="curiosity",
            content=interest,
        )
        # Surface the latest few interests on the identity so they reach the
        # prompt; cap to keep the self-model compact.
        existing = self.identity.get().get("interests") or []
        merged = [interest] + [item for item in existing if item != interest]
        self.identity.update({"interests": merged[:5]})
        return interest

    async def _maybe_propose(self, tick_count: int) -> dict[str, Any] | None:
        """Occasionally surface a self-improvement proposal (master spec §8).

        Gated by ``propose_every`` and skipped if a proposal is already waiting,
        so pending proposals never pile up. The proposal is created as
        ``pending`` — Odin never applies its own change without human approval.
        """
        if self.improvement is None or self.propose_every <= 0:
            return None
        if tick_count % self.propose_every != 0:
            return None
        if self.improvement.list(status="pending"):
            return None
        record = await self.improvement.propose(
            "memory",
            "persona",
            rationale=f"heartbeat {tick_count}: periodic self-review of voice",
        )
        return {"proposal_id": record.proposal_id, "target": record.target}

    # --- background loop ---------------------------------------------------

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="jarvis-heartbeat")

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
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
                return
            except TimeoutError:
                pass
            try:
                await self.tick()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - the loop must survive any tick error
                self.last_error = str(exc)

    async def _safe(self, coro) -> Any:
        """Run a best-effort tick sub-step, swallowing failures into last_error."""
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001 - one weak step must not abort the tick
            self.last_error = str(exc)
            return None

    def _next_tick_count(self) -> int:
        return int(self.settings.read().get(TICK_COUNT_KEY, 0) or 0) + 1

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(event_type, payload)
