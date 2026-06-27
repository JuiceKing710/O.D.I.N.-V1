from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.heartbeat import HeartbeatEngine
from jarvis.backend.core.identity_manager import IdentityManager
from jarvis.backend.core.improvement_manager import ImprovementManager
from jarvis.backend.core.lm_provider import EchoLMProvider
from jarvis.backend.core.memory_consolidator import MemoryConsolidator
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.safety_switch import SafetySwitch
from jarvis.backend.core.settings_store import SettingsStore


class HeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory = MemoryManager(base / "jarvis.db")
        self.settings = SettingsStore(base / "settings.json")
        self.events = EventBus()
        self.provider = EchoLMProvider()
        self.identity = IdentityManager(self.memory, self.events)
        self.consolidator = MemoryConsolidator(
            self.memory, self.provider, self.settings, self.events, enabled=False
        )
        self.safety = SafetySwitch(self.settings, self.events)
        self.engine = HeartbeatEngine(
            self.memory,
            self.provider,
            self.identity,
            self.consolidator,
            self.settings,
            safety_switch=self.safety,
            event_bus=self.events,
            enabled=False,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event_types(self) -> list[str]:
        return [event.type for event in self.events.history()]

    def test_tick_advances_count_and_updates_identity(self) -> None:
        result = asyncio.run(self.engine.tick())
        self.assertFalse(result["skipped"])
        self.assertEqual(result["tick"], 1)
        self.assertEqual(self.engine.status()["tick_count"], 1)
        self.assertIn("heartbeat 1", self.identity.get()["narrative"])
        self.assertIn("heartbeat.tick", self._event_types())

    def test_tick_records_a_curiosity_document(self) -> None:
        asyncio.run(self.engine.tick())
        user = self.memory.get_or_create_user("local-user")
        sources = [doc.source for doc in self.memory.list_documents(user.user_id)]
        self.assertIn("curiosity", sources)

    def test_tick_is_noop_while_halted(self) -> None:
        self.safety.engage(reason="halt")
        result = asyncio.run(self.engine.tick())
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "emergency_stop")
        self.assertEqual(self.engine.status()["tick_count"], 0)
        self.assertIn("heartbeat.skipped", self._event_types())

    def test_tick_reflects_recent_conversation(self) -> None:
        user = self.memory.get_or_create_user("local-user")
        convo = self.memory.create_conversation(user.user_id, title="greeting")
        self.memory.add_message(convo.convo_id, "user", "hello there")
        self.memory.add_message(convo.convo_id, "assistant", "hi")

        result = asyncio.run(self.engine.tick())

        self.assertEqual(result["reflected_conversation"], convo.convo_id)
        self.assertTrue(self.memory.list_reflection_summaries(convo.convo_id))

    def _engine_with_improvement(self, propose_every: int) -> HeartbeatEngine:
        improvement = ImprovementManager(
            self.memory, self.settings, self.provider, self.safety, self.events
        )
        return HeartbeatEngine(
            self.memory,
            self.provider,
            self.identity,
            self.consolidator,
            self.settings,
            safety_switch=self.safety,
            event_bus=self.events,
            improvement=improvement,
            enabled=False,
            propose_every=propose_every,
        )

    def test_default_engine_never_proposes(self) -> None:
        # The base engine (no improvement manager, propose_every=0) stays quiet.
        result = asyncio.run(self.engine.tick())
        self.assertIsNone(result["improvement_proposal"])
        self.assertEqual(self.memory.list_proposals(), [])

    def test_heartbeat_surfaces_pending_proposal(self) -> None:
        engine = self._engine_with_improvement(propose_every=1)
        result = asyncio.run(engine.tick())
        self.assertIsNotNone(result["improvement_proposal"])
        pending = self.memory.list_proposals(status="pending")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].target, "persona")

    def test_heartbeat_does_not_pile_up_proposals(self) -> None:
        engine = self._engine_with_improvement(propose_every=1)
        asyncio.run(engine.tick())
        asyncio.run(engine.tick())
        # A proposal is already pending, so the second tick adds none.
        self.assertEqual(len(self.memory.list_proposals(status="pending")), 1)

    def test_proposal_cadence_is_respected(self) -> None:
        engine = self._engine_with_improvement(propose_every=2)
        first = asyncio.run(engine.tick())  # tick 1 — not a multiple of 2
        self.assertIsNone(first["improvement_proposal"])
        second = asyncio.run(engine.tick())  # tick 2 — proposes
        self.assertIsNotNone(second["improvement_proposal"])

    def test_goal_crud_round_trips(self) -> None:
        user = self.memory.get_or_create_user("local-user")
        goal = self.memory.create_goal(user.user_id, "ship the heartbeat")
        self.assertEqual(goal.status, "active")
        self.assertEqual(len(self.memory.list_goals(user.user_id, status="active")), 1)

        self.memory.update_goal(user.user_id, goal.goal_id, status="done")
        self.assertEqual(self.memory.list_goals(user.user_id, status="active"), [])
        done = self.memory.list_goals(user.user_id, status="done")
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0].status, "done")


if __name__ == "__main__":
    unittest.main()
