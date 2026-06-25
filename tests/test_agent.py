from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse
from jarvis.backend.core.agent_manager import DeepResearchAgent
from jarvis.backend.core.bot_manager import BotManager
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.lm_provider import EchoLMProvider
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import (
    Permission,
    PermissionDecision,
    PermissionManager,
)


class RecordingEventBus(EventBus):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_type, payload, *, transient=False):
        self.events.append((event_type, payload))
        return super().publish(event_type, payload, transient=transient)

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.events]


class FakeResearchBot(Bot):
    """Stand-in for ResearchBot that still enforces access_network.

    Enforcing the permission is the point: it proves the agent's scope grant is
    what lets the run proceed unattended, rather than the gate being bypassed.
    """

    name = "research"
    description = "fake research bot"

    def __init__(self, permission_manager, audit_logger) -> None:
        super().__init__(permission_manager, audit_logger)
        self.searches: list[str] = []
        self.fetches: list[str] = []

    def capabilities(self) -> list[str]:
        return ["search", "fetch"]

    async def on_request(self, request: BotRequest) -> BotResponse:
        try:
            self.permission_manager.require_allowed(
                "access_network", actor=request.sender, reason="fake research"
            )
        except PermissionError as exc:
            return self.permission_response(exc)
        if request.action == "search":
            query = str(request.payload.get("text", ""))
            self.searches.append(query)
            index = len(self.searches)
            return BotResponse(
                ok=True,
                payload={
                    "results": [
                        {"title": f"Result for {query}", "url": f"https://example.com/{index}"}
                    ]
                },
            )
        if request.action == "fetch":
            url = str(request.payload.get("text", ""))
            self.fetches.append(url)
            return BotResponse(ok=True, payload={"text": f"Readable page text from {url}."})
        return BotResponse(ok=False, error=f"bad action {request.action}")


class ScriptedLMProvider(EchoLMProvider):
    """Returns a query list for the plan call and a report for the synthesis call."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    async def generate(self, text, context, metadata=None, history=None) -> str:
        self.prompts.append(text)
        if "SOURCES:" in text:
            return "Grounded report using [1] and [2]."
        return '["alpha question", "beta question"]'


def _permission_manager(network=PermissionDecision.PROMPT, storage=None) -> PermissionManager:
    return PermissionManager(
        {
            "access_network": Permission("access_network", "network", network),
            "execute_scripts": Permission(
                "execute_scripts", "scripts", PermissionDecision.DENIED
            ),
        },
        storage_path=storage,
    )


def _build_agent(permission_manager, event_bus):
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    audit_logger = AuditLogger(base / "audit.log")
    memory = MemoryManager(base / "jarvis.db")
    bot_manager = BotManager(permission_manager, audit_logger, event_bus=event_bus)
    research = FakeResearchBot(permission_manager, audit_logger)
    bot_manager.register(research)
    agent = DeepResearchAgent(
        lm_provider=ScriptedLMProvider(),
        bot_manager=bot_manager,
        memory=memory,
        audit_logger=audit_logger,
        event_bus=event_bus,
    )
    return agent, research, memory, tmp


class PermissionScopeTests(unittest.TestCase):
    def test_scope_allows_prompt_permission_then_reverts(self) -> None:
        manager = _permission_manager()
        # Outside a scope, a prompt permission raises (creates an approval request).
        with self.assertRaises(PermissionError):
            manager.require_allowed("access_network", actor="agent", reason="x")
        with manager.scope(["access_network"]):
            manager.require_allowed("access_network", actor="agent", reason="x")  # no raise
        # Closed again -> gated once more.
        with self.assertRaises(PermissionError):
            manager.require_allowed("access_network", actor="agent", reason="y")

    def test_scope_never_overrides_a_hard_denied(self) -> None:
        manager = _permission_manager()
        with manager.scope(["execute_scripts"]):
            with self.assertRaises(PermissionError):
                manager.require_allowed("execute_scripts", actor="agent", reason="z")

    def test_scope_closes_even_on_error(self) -> None:
        manager = _permission_manager()
        with self.assertRaises(ValueError):
            with manager.scope(["access_network"]):
                raise ValueError("boom")
        self.assertFalse(manager._in_open_scope("access_network"))


class DeepResearchAgentTests(unittest.TestCase):
    def test_runs_full_pipeline_unattended(self) -> None:
        event_bus = RecordingEventBus()
        manager = _permission_manager()
        agent, research, memory, tmp = _build_agent(manager, event_bus)
        try:
            result = asyncio.run(agent.run_research("what is odysseus", "tester"))
        finally:
            tmp.cleanup()

        # The plan produced two queries; both were searched and both pages read,
        # all without a single permission prompt being left pending.
        self.assertEqual(research.searches, ["alpha question", "beta question"])
        self.assertEqual(len(research.fetches), 2)
        self.assertEqual(manager.pending_requests(), [])
        self.assertIn("Grounded report", result["report"])
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["queries"], ["alpha question", "beta question"])

    def test_emits_progress_events_and_completes_task(self) -> None:
        event_bus = RecordingEventBus()
        manager = _permission_manager()
        agent, _research, memory, tmp = _build_agent(manager, event_bus)
        try:
            result = asyncio.run(agent.run_research("topic", "tester"))
            user = memory.get_or_create_user("tester")
            tasks = memory.list_tasks(user.user_id)
        finally:
            tmp.cleanup()

        types = event_bus.types()
        self.assertEqual(types[0], "agent.started")
        self.assertIn("agent.plan", types)
        self.assertIn("agent.step", types)
        self.assertEqual(types[-1], "agent.complete")
        # The run is persisted as a completed task carrying the report.
        task = next(task for task in tasks if task.task_id == result["task_id"])
        self.assertEqual(task.status, "complete")

    def test_start_research_is_pollable_in_background(self) -> None:
        event_bus = RecordingEventBus()
        manager = _permission_manager()
        agent, _research, _memory, tmp = _build_agent(manager, event_bus)
        try:
            async def scenario():
                snapshot = agent.start_research("topic", "tester")
                self.assertEqual(snapshot["status"], "running")
                run_id = snapshot["run_id"]
                for _ in range(200):
                    run = agent.get_run(run_id)
                    if run["status"] != "running":
                        return run
                    await asyncio.sleep(0.005)
                return agent.get_run(run_id)

            run = asyncio.run(scenario())
        finally:
            tmp.cleanup()

        self.assertEqual(run["status"], "complete")
        self.assertIn("Grounded report", run["report"])
        self.assertEqual(len(run["sources"]), 2)
        self.assertTrue(run["steps"])

    def test_get_run_unknown_returns_none(self) -> None:
        event_bus = RecordingEventBus()
        manager = _permission_manager()
        agent, _research, _memory, tmp = _build_agent(manager, event_bus)
        try:
            self.assertIsNone(agent.get_run("nope"))
        finally:
            tmp.cleanup()

    def test_empty_goal_rejected(self) -> None:
        event_bus = RecordingEventBus()
        manager = _permission_manager()
        agent, _research, _memory, tmp = _build_agent(manager, event_bus)
        try:
            with self.assertRaises(ValueError):
                asyncio.run(agent.run_research("   ", "tester"))
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
