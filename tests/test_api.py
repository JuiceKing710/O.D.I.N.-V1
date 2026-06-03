from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis.backend.api.main import create_app
from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.core.app_factory import get_core, get_settings_store
from jarvis.backend.core.bot_manager import BotManager
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import EchoLMProvider
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import Permission, PermissionDecision, PermissionManager


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        permission_manager = PermissionManager(
            {
                "execute_scripts": Permission(
                    "execute_scripts", "execute scripts", PermissionDecision.DENIED
                )
            }
        )
        audit_logger = AuditLogger(base / "audit.log")
        bot_manager = BotManager(permission_manager, audit_logger)
        bot_manager.register(CodeBot(permission_manager, audit_logger))
        self.core = JarvisCore(
            memory=MemoryManager(base / "jarvis.db"),
            bot_manager=bot_manager,
            lm_provider=EchoLMProvider(),
            audit_logger=audit_logger,
        )
        self.settings = SettingsStore(base / "settings.json")
        app = create_app()
        app.dependency_overrides[get_core] = lambda: self.core
        app.dependency_overrides[get_settings_store] = lambda: self.settings
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_chat_endpoint_persists_and_returns_reply(self) -> None:
        response = self.client.post(
            "/api/v1/chat",
            json={"message": "hello from api", "username": "api-user"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["conversation_id"], 1)
        self.assertIn("I heard: hello from api", body["reply"])

    def test_task_endpoints_create_and_list_tasks(self) -> None:
        created = self.client.post(
            "/api/v1/tasks",
            json={"username": "api-user", "name": "Ship scaffold", "description": "baseline"},
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["status"], "pending")

        listed = self.client.get("/api/v1/tasks", params={"username": "api-user"})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

    def test_bot_endpoint_returns_404_for_unknown_bot(self) -> None:
        response = self.client.post(
            "/api/v1/bot/missing/exec",
            json={"action": "noop", "payload": {}},
        )
        self.assertEqual(response.status_code, 404)

    def test_settings_round_trip(self) -> None:
        updated = self.client.put("/api/v1/settings", json={"theme": "dark"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["theme"], "dark")

        fetched = self.client.get("/api/v1/settings")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["theme"], "dark")

    def test_local_frontend_cors_preflight(self) -> None:
        response = self.client.options(
            "/api/v1/chat",
            headers={
                "Origin": "http://127.0.0.1:4173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:4173")


if __name__ == "__main__":
    unittest.main()
