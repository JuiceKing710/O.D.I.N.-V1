from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.bots.system_bot import SystemBot
from jarvis.backend.core.bot_manager import BotManager, BotMessage
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.safety_switch import SafetySwitch
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import Permission, PermissionDecision, PermissionManager


class SafetySwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.settings = SettingsStore(base / "settings.json")
        self.audit = AuditLogger(base / "audit.log")
        self.events = EventBus()
        self.switch = SafetySwitch(self.settings, event_bus=self.events, audit_logger=self.audit)
        self.permissions = PermissionManager(
            {
                "execute_scripts": Permission(
                    "execute_scripts", "execute scripts", PermissionDecision.ALLOWED
                ),
                "read_files": Permission(
                    "read_files", "read files", PermissionDecision.ALLOWED
                ),
            }
        )
        self.bot_manager = BotManager(
            self.permissions, self.audit, event_bus=self.events, safety_switch=self.switch
        )
        self.bot_manager.register(SystemBot(self.permissions, self.audit))
        self.bot_manager.register(CodeBot(self.permissions, self.audit))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _dispatch(self, recipient: str, action: str, payload: dict) -> object:
        return asyncio.run(
            self.bot_manager.dispatch(
                BotMessage(sender="user", recipient=recipient, action=action, payload=payload)
            )
        )

    def test_engage_release_round_trips_and_persists(self) -> None:
        self.assertFalse(self.switch.is_engaged())
        status = self.switch.engage(reason="testing")
        self.assertTrue(status["engaged"])
        self.assertEqual(status["reason"], "testing")
        # Persisted: a freshly constructed switch over the same settings sees it.
        self.assertTrue(SafetySwitch(self.settings).is_engaged())
        released = self.switch.release()
        self.assertFalse(released["engaged"])
        self.assertFalse(SafetySwitch(self.settings).is_engaged())

    def test_engage_writes_audit_entry(self) -> None:
        self.switch.engage(reason="kill it")
        actions = [event["action"] for event in self.audit.list_events()]
        self.assertIn("safety:emergency_stop", actions)

    def test_high_impact_bot_is_refused_while_halted(self) -> None:
        self.switch.engage(reason="halt")
        response = self._dispatch("system", "execute", {"text": "printf hello"})
        self.assertIsNotNone(response)
        self.assertFalse(response.ok)
        self.assertIn("halted", (response.error or "").lower())

    def test_read_only_bot_still_runs_while_halted(self) -> None:
        path = Path(self.tmp.name) / "sample.py"
        path.write_text("class Ready:\n    pass\n", encoding="utf-8")
        self.switch.engage(reason="halt")
        response = self._dispatch("code", "analyze", {"path": str(path)})
        self.assertIsNotNone(response)
        self.assertTrue(response.ok)

    def test_high_impact_bot_runs_again_after_resume(self) -> None:
        self.switch.engage(reason="halt")
        self.switch.release()
        response = self._dispatch("system", "execute", {"text": "printf hello"})
        self.assertIsNotNone(response)
        self.assertTrue(response.ok)


if __name__ == "__main__":
    unittest.main()
