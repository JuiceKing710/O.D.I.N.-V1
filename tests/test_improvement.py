from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.improvement_manager import ImprovementManager
from jarvis.backend.core.lm_provider import EchoLMProvider
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.safety_switch import SafetySwitch
from jarvis.backend.core.settings_store import SettingsStore


class ImprovementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory = MemoryManager(base / "jarvis.db")
        self.settings = SettingsStore(base / "settings.json")
        self.events = EventBus()
        self.safety = SafetySwitch(self.settings, self.events)
        self.improvements = ImprovementManager(
            self.memory,
            self.settings,
            EchoLMProvider(),
            safety_switch=self.safety,
            event_bus=self.events,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _propose_memory(self, value: str = "Odin is sharper and warmer now."):
        return asyncio.run(
            self.improvements.propose("memory", "persona", proposed_value=value)
        )

    def test_propose_captures_current_value_and_is_pending(self) -> None:
        record = self._propose_memory()
        self.assertEqual(record.status, "pending")
        self.assertEqual(record.kind, "memory")
        # current_value is the live persona block before the change.
        self.assertEqual(record.current_value, self.memory.get_memory_blocks()["persona"])

    def test_apply_requires_approval_first(self) -> None:
        record = self._propose_memory()
        with self.assertRaises(ValueError):
            self.improvements.apply(record.proposal_id)

    def test_approve_then_apply_mutates_target(self) -> None:
        record = self._propose_memory("Odin: crisp, kind, and decisive.")
        self.improvements.approve(record.proposal_id)
        self.improvements.apply(record.proposal_id)
        self.assertEqual(
            self.memory.get_memory_blocks()["persona"], "Odin: crisp, kind, and decisive."
        )

    def test_revert_restores_prior_value(self) -> None:
        before = self.memory.get_memory_blocks()["persona"]
        record = self._propose_memory("temporary persona")
        self.improvements.approve(record.proposal_id)
        self.improvements.apply(record.proposal_id)
        self.improvements.revert(record.proposal_id)
        self.assertEqual(self.memory.get_memory_blocks()["persona"], before)

    def test_emergency_stop_blocks_apply(self) -> None:
        record = self._propose_memory()
        self.improvements.approve(record.proposal_id)
        self.safety.engage(reason="halt")
        with self.assertRaises(ValueError):
            self.improvements.apply(record.proposal_id)

    def test_setting_value_round_trips_with_type(self) -> None:
        record = asyncio.run(
            self.improvements.propose("setting", "turbo_mode", proposed_value="true")
        )
        self.improvements.approve(record.proposal_id)
        self.improvements.apply(record.proposal_id)
        self.assertIs(self.settings.read()["turbo_mode"], True)
        self.improvements.revert(record.proposal_id)
        self.assertIs(self.settings.read()["turbo_mode"], False)

    def test_reject_blocks_apply(self) -> None:
        record = self._propose_memory()
        self.improvements.reject(record.proposal_id)
        with self.assertRaises(ValueError):
            self.improvements.apply(record.proposal_id)

    def test_propose_publishes_event(self) -> None:
        self._propose_memory()
        self.assertIn("improvement.proposed", [event.type for event in self.events.history()])


if __name__ == "__main__":
    unittest.main()
