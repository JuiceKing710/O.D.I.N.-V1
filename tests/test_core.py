from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse
from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.core.bot_manager import BotManager, BotMessage
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import EchoLMProvider
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.vector_store import InMemoryVectorStore, VectorStoreInterface
from jarvis.backend.core.voice_manager import InterruptionConfig, VoiceManager, VoiceState
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import Permission, PermissionDecision, PermissionManager
from jarvis.backend.utils.reflection import ReflectionEngine


class BrokenVectorStore(VectorStoreInterface):
    @property
    def enabled(self) -> bool:
        return True

    def upsert_message(
        self, message_id: int, content: str, metadata: dict[str, Any]
    ) -> str | None:
        raise RuntimeError("vector write failed")

    def upsert_document(
        self, document_id: str, content: str, metadata: dict[str, Any]
    ) -> str | None:
        raise RuntimeError("vector write failed")

    def upsert_task(self, task_id: int, content: str, metadata: dict[str, Any]) -> str | None:
        raise RuntimeError("vector write failed")

    def query(self, collection: str, text: str, limit: int):
        raise RuntimeError("vector query failed")

    def health(self) -> dict[str, Any]:
        return {"enabled": True, "provider": "broken"}


class SlowBot(Bot):
    name = "slow"
    description = "Sleeps long enough to test retry behavior."

    def __init__(self, permission_manager, audit_logger) -> None:
        super().__init__(permission_manager, audit_logger)
        self.attempts = 0

    async def on_request(self, request: BotRequest) -> BotResponse:
        self.attempts += 1
        await asyncio.sleep(0.05)
        return BotResponse(ok=True)


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.permissions = PermissionManager(
            {
                "read_files": Permission("read_files", "read files", PermissionDecision.PROMPT),
                "access_network": Permission(
                    "access_network", "access network", PermissionDecision.PROMPT
                ),
                "execute_scripts": Permission(
                    "execute_scripts", "execute scripts", PermissionDecision.DENIED
                ),
            }
        )
        self.audit = AuditLogger(base / "audit.log")
        self.memory = MemoryManager(base / "jarvis.db")
        self.bot_manager = BotManager(self.permissions, self.audit)
        self.bot_manager.register(CodeBot(self.permissions, self.audit))
        self.core = JarvisCore(
            memory=self.memory,
            bot_manager=self.bot_manager,
            lm_provider=EchoLMProvider(),
            audit_logger=self.audit,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_handle_message_persists_conversation(self) -> None:
        result = asyncio.run(self.core.handle_message("remember the blue folder", "tester"))
        self.assertEqual(result["conversation_id"], 1)
        user = self.memory.get_or_create_user("tester")
        matches = self.memory.query_messages(user.user_id, "blue", limit=10)
        self.assertEqual(len(matches), 2)

    def test_bot_command_dispatches_registered_bot(self) -> None:
        result = asyncio.run(self.core.handle_message("/code analyze main.py", "tester"))
        self.assertEqual(result["bot"], "code")
        self.assertIn("Code analysis request accepted", result["reply"])

    def test_bot_manager_returns_none_for_unknown_bot(self) -> None:
        response = asyncio.run(
            self.bot_manager.dispatch(
                BotMessage(sender="test", recipient="missing", action="noop", payload={})
            )
        )
        self.assertIsNone(response)

    def test_permission_defaults_are_enforced(self) -> None:
        with self.assertRaises(PermissionError):
            self.permissions.require_allowed("execute_scripts")

    def test_vector_failure_falls_back_to_sqlite_query(self) -> None:
        memory = MemoryManager(Path(self.tmp.name) / "broken.db", vector_store=BrokenVectorStore())
        user = memory.get_or_create_user("vector-user")
        convo = memory.create_conversation(user.user_id)
        memory.add_message(convo.convo_id, "user", "fallback keyword")

        matches = memory.query_messages(user.user_id, "keyword", limit=5)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].content, "fallback keyword")

    def test_hybrid_memory_lookup_uses_vector_results(self) -> None:
        memory = MemoryManager(Path(self.tmp.name) / "vector.db", vector_store=InMemoryVectorStore())
        user = memory.get_or_create_user("vector-user")
        convo = memory.create_conversation(user.user_id)
        memory.add_message(convo.convo_id, "user", "ordinary sqlite text")
        memory.add_message(convo.convo_id, "assistant", "semantic nebula memory")

        matches = memory.query_messages(user.user_id, "nebula", limit=5)

        self.assertEqual(matches[0].content, "semantic nebula memory")
        self.assertTrue(matches[0].embedding_id)

    def test_lm_provider_loads_selected_model(self) -> None:
        provider = EchoLMProvider()

        result = asyncio.run(provider.load_model("echo-alt"))

        self.assertEqual(result.id, "echo-alt")
        self.assertTrue(asyncio.run(provider.list_models())[0].loaded)

    def test_bot_acl_denies_disallowed_recipient(self) -> None:
        manager = BotManager(self.permissions, self.audit, acl={"tester": {"file"}})
        manager.register(CodeBot(self.permissions, self.audit))

        response = asyncio.run(
            manager.dispatch(BotMessage(sender="tester", recipient="code", action="analyze"))
        )

        self.assertIsNotNone(response)
        self.assertFalse(response.ok)
        self.assertIn("ACL", response.error)

    def test_bot_timeout_retries_once(self) -> None:
        manager = BotManager(
            self.permissions,
            self.audit,
            timeout_seconds=0.01,
            retry_count=1,
        )
        bot = SlowBot(self.permissions, self.audit)
        manager.register(bot)

        response = asyncio.run(
            manager.dispatch(BotMessage(sender="tester", recipient="slow", action="wait"))
        )

        self.assertIsNotNone(response)
        self.assertFalse(response.ok)
        self.assertEqual(bot.attempts, 2)

    def test_voice_interruption_hysteresis(self) -> None:
        voice = VoiceManager(InterruptionConfig(energy_threshold=0.5, hold_frames=2, release_frames=2))
        voice.transition(VoiceState.SPEAKING)

        self.assertFalse(voice.detect_interruption(0.8))
        self.assertTrue(voice.detect_interruption(0.8))
        self.assertTrue(voice.detect_interruption(0.1))
        self.assertFalse(voice.detect_interruption(0.1))

    def test_reflection_summary_is_persisted(self) -> None:
        user = self.memory.get_or_create_user("reflect-user")
        convo = self.memory.create_conversation(user.user_id)
        self.memory.add_message(convo.convo_id, "user", "summarize this")
        engine = ReflectionEngine(self.memory, EchoLMProvider())

        summary = asyncio.run(engine.summarize_conversation(user.user_id, convo.convo_id))
        summaries = self.memory.list_reflection_summaries(convo.convo_id)

        self.assertEqual(summary.reflection_id, summaries[0].reflection_id)
        self.assertIn("I heard", summaries[0].summary)


if __name__ == "__main__":
    unittest.main()
