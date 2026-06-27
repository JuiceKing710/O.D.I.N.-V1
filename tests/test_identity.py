from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.identity_manager import IdentityManager
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.utils.audit_logging import AuditLogger


class _RecordingProvider:
    """Duck-typed LLM stub that captures the context it is handed so tests can
    assert what reached the prompt."""

    def __init__(self) -> None:
        self.last_context: list[str] = []

    async def generate_stream(self, prompt, context=None, metadata=None, history=None):
        self.last_context = list(context or [])
        yield "ok"


class _NullBotManager:
    """Never matches a bot, so chat falls through to the LLM path."""

    def get(self, name):  # noqa: ANN001 - test stub
        return None


class IdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory = MemoryManager(base / "jarvis.db")
        self.events = EventBus()
        self.identity = IdentityManager(self.memory, event_bus=self.events)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_defaults_present_before_any_write(self) -> None:
        identity = self.identity.get()
        self.assertEqual(identity["mood"], "steady")
        self.assertIn("steady", identity["traits"])
        self.assertEqual(identity["interests"], [])

    def test_update_narrative_round_trips_and_lists_persist(self) -> None:
        self.identity.update({"narrative": "auditing the codebase", "interests": ["runes"]})
        reloaded = IdentityManager(self.memory).get()
        self.assertEqual(reloaded["narrative"], "auditing the codebase")
        self.assertEqual(reloaded["interests"], ["runes"])

    def test_update_publishes_event(self) -> None:
        self.identity.set_narrative("thinking", mood="curious")
        events = [event for event in self.events.history() if event.type == "identity.updated"]
        self.assertTrue(events)
        self.assertEqual(events[-1].payload["mood"], "curious")

    def test_unknown_keys_are_ignored(self) -> None:
        self.identity.update({"narrative": "x", "secret_backdoor": "y"})
        self.assertNotIn("secret_backdoor", self.identity.get())

    def test_identity_context_reflects_narrative(self) -> None:
        self.identity.set_narrative("reviewing PR #3")
        context = self.memory.identity_context()
        self.assertEqual(len(context), 1)
        self.assertIn("reviewing PR #3", context[0])

    def test_identity_block_reaches_chat_prompt(self) -> None:
        self.identity.set_narrative("guarding the gate")
        provider = _RecordingProvider()
        core = JarvisCore(
            memory=self.memory,
            bot_manager=_NullBotManager(),
            lm_provider=provider,
            audit_logger=AuditLogger(Path(self.tmp.name) / "audit.log"),
        )
        asyncio.run(core.handle_message("hello", "tester"))
        self.assertTrue(any("guarding the gate" in line for line in provider.last_context))


if __name__ == "__main__":
    unittest.main()
