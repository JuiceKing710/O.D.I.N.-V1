from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.core.bot_manager import BotManager, BotMessage
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import EchoLMProvider
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import Permission, PermissionDecision, PermissionManager


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


if __name__ == "__main__":
    unittest.main()

