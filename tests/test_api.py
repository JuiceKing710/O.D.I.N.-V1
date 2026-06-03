from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis.backend.api.main import create_app
from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.bots.system_bot import SystemBot
from jarvis.backend.core.app_factory import (
    get_core,
    get_event_bus,
    get_recovery_manager,
    get_settings_store,
)
from jarvis.backend.core.bot_manager import BotManager
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import EchoLMProvider, ModelInfo, ProviderStatus
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.recovery_manager import RecoveryManager
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.core.vector_store import NullVectorStore
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import Permission, PermissionDecision, PermissionManager


class FailingLMProvider(EchoLMProvider):
    async def generate(self, text, context, metadata=None) -> str:
        raise RuntimeError("Ollama is not running at http://127.0.0.1:11434. Run `ollama serve`.")

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider="ollama",
            base_url="http://127.0.0.1:11434",
            available=False,
            selected_model=None,
            error="Ollama is not running at http://127.0.0.1:11434. Run `ollama serve`.",
        )


class StatusLMProvider(EchoLMProvider):
    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="llama3.2:latest", provider="ollama", loaded=True)]

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider="ollama",
            base_url="http://127.0.0.1:11434",
            available=True,
            selected_model="llama3.2:latest",
        )


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        permission_manager = PermissionManager(
            {
                "execute_scripts": Permission(
                    "execute_scripts", "execute scripts", PermissionDecision.DENIED
                ),
                "read_files": Permission("read_files", "read files", PermissionDecision.PROMPT),
            }
        )
        self.event_bus = EventBus()
        audit_logger = AuditLogger(base / "audit.log")
        self.memory = MemoryManager(base / "jarvis.db")
        bot_manager = BotManager(permission_manager, audit_logger, event_bus=self.event_bus)
        bot_manager.register(CodeBot(permission_manager, audit_logger))
        bot_manager.register(SystemBot(permission_manager, audit_logger))
        self.core = JarvisCore(
            memory=self.memory,
            bot_manager=bot_manager,
            lm_provider=EchoLMProvider(),
            audit_logger=audit_logger,
            event_bus=self.event_bus,
        )
        self.settings = SettingsStore(base / "settings.json")
        self.recovery = RecoveryManager(base / "jarvis.db", base / "backups", NullVectorStore())
        app = create_app()
        app.dependency_overrides[get_core] = lambda: self.core
        app.dependency_overrides[get_event_bus] = lambda: self.event_bus
        app.dependency_overrides[get_recovery_manager] = lambda: self.recovery
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

    def test_chat_endpoint_reports_lm_provider_failure(self) -> None:
        self.core.lm_provider = FailingLMProvider()

        response = self.client.post(
            "/api/v1/chat",
            json={"message": "hello from api", "username": "api-user"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("Language model provider unavailable", response.json()["detail"])
        self.assertIn("ollama serve", response.json()["detail"])

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

    def test_bot_endpoint_returns_permission_denial(self) -> None:
        response = self.client.post(
            "/api/v1/bot/system/exec",
            json={"action": "execute", "payload": {"text": "date"}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])
        self.assertIn("denied", response.json()["error"])

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

    def test_invalid_conversation_returns_404(self) -> None:
        response = self.client.post(
            "/api/v1/chat",
            json={"message": "hello", "username": "api-user", "conversation_id": 99},
        )
        self.assertEqual(response.status_code, 404)

    def test_conversation_endpoints_list_history_and_messages(self) -> None:
        first = self.client.post(
            "/api/v1/chat",
            json={"message": "first conversation", "username": "history-user"},
        )
        second = self.client.post(
            "/api/v1/chat",
            json={"message": "second conversation", "username": "history-user"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        listed = self.client.get("/api/v1/conversations", params={"username": "history-user"})

        self.assertEqual(listed.status_code, 200)
        conversations = listed.json()
        self.assertEqual(len(conversations), 2)
        self.assertEqual(conversations[0]["convo_id"], second.json()["conversation_id"])
        self.assertEqual(conversations[0]["message_count"], 2)

        messages = self.client.get(
            f"/api/v1/conversations/{first.json()['conversation_id']}/messages",
            params={"username": "history-user"},
        )

        self.assertEqual(messages.status_code, 200)
        self.assertEqual([message["role"] for message in messages.json()], ["user", "assistant"])

    def test_conversation_messages_reject_wrong_user(self) -> None:
        created = self.client.post(
            "/api/v1/chat",
            json={"message": "private conversation", "username": "owner-user"},
        )

        response = self.client.get(
            f"/api/v1/conversations/{created.json()['conversation_id']}/messages",
            params={"username": "other-user"},
        )

        self.assertEqual(response.status_code, 404)

    def test_model_load_endpoint_updates_loaded_model(self) -> None:
        response = self.client.post("/api/v1/models/load", json={"model_name": "echo-alt"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["models"][0]["id"], "echo-alt")
        self.assertTrue(body["models"][0]["loaded"])
        self.assertEqual(body["provider"]["provider"], "builtin")

    def test_models_endpoint_reports_provider_status(self) -> None:
        self.core.lm_provider = StatusLMProvider()

        response = self.client.get("/api/v1/models")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provider"]["provider"], "ollama")
        self.assertTrue(body["provider"]["available"])
        self.assertEqual(body["provider"]["selected_model"], "llama3.2:latest")
        self.assertEqual(body["models"][0]["provider"], "ollama")

    def test_websocket_receives_chat_event(self) -> None:
        with self.client.websocket_connect("/api/v1/events") as websocket:
            response = self.client.post(
                "/api/v1/chat",
                json={"message": "socket hello", "username": "socket-user"},
            )
            self.assertEqual(response.status_code, 200)
            event = websocket.receive_json()

        self.assertEqual(event["type"], "chat.message")
        self.assertEqual(event["payload"]["role"], "user")
        self.assertEqual(event["payload"]["content"], "socket hello")

    def test_recovery_integrity_reports_sqlite_health(self) -> None:
        self.memory.get_or_create_user("health-user")

        response = self.client.get("/api/v1/recovery/integrity")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["sqlite_ok"])

    def test_recovery_backup_missing_database_returns_404(self) -> None:
        missing = Path(self.tmp.name) / "missing.db"
        app = self.client.app
        app.dependency_overrides[get_recovery_manager] = lambda: RecoveryManager(
            missing,
            Path(self.tmp.name) / "backups",
            NullVectorStore(),
        )

        response = self.client.post("/api/v1/recovery/backups")

        self.assertEqual(response.status_code, 404)
        app.dependency_overrides[get_recovery_manager] = lambda: self.recovery


if __name__ == "__main__":
    unittest.main()
