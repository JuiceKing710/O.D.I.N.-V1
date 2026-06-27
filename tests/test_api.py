from __future__ import annotations

import base64
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from jarvis.backend.utils.auth import (
    TokenAuthMiddleware,
    auth_required,
    resolve_api_token,
)

from jarvis.backend.api.main import create_app
from jarvis.backend.core.agent_manager import DeepResearchAgent
from jarvis.backend.core.app_factory import get_agent_manager
from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.bots.file_bot import FileBot
from jarvis.backend.bots.image_bot import ImageBot
from jarvis.backend.bots.system_bot import SystemBot
from jarvis.backend.core.app_factory import (
    get_backup_scheduler,
    get_core,
    get_event_bus,
    get_heartbeat_engine,
    get_image_manager,
    get_improvement_manager,
    get_permission_manager,
    get_recovery_manager,
    get_safety_switch,
    get_settings_store,
    get_system_monitor,
    get_vision_manager,
    get_voice_manager,
    get_wake_word_listener,
)
from jarvis.backend.core.image_manager import ImageManager, StubImageAdapter
from jarvis.backend.core.system_monitor import SystemMonitor
from jarvis.backend.core.backup_scheduler import BackupScheduler
from jarvis.backend.core.bot_manager import BotManager
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import EchoLMProvider, ModelInfo, ProviderStatus
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.recovery_manager import RecoveryManager
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.core.safety_switch import SafetySwitch
from jarvis.backend.core.heartbeat import HeartbeatEngine
from jarvis.backend.core.identity_manager import IdentityManager
from jarvis.backend.core.improvement_manager import ImprovementManager
from jarvis.backend.core.memory_consolidator import MemoryConsolidator
from jarvis.backend.core.vector_store import NullVectorStore
from jarvis.backend.core.vision_manager import VisionManager
from jarvis.backend.core.voice_manager import VoiceManager, WhisperCliSpeechToTextAdapter
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import Permission, PermissionDecision, PermissionManager

from tests.test_agent import FakeResearchBot, ScriptedLMProvider


class FailingLMProvider(EchoLMProvider):
    async def generate(self, text, context, metadata=None, history=None) -> str:
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


class FakeSpeechToTextAdapter:
    name = "fake-stt"
    configured = True

    def transcribe(self, audio_path: Path) -> str:
        return audio_path.read_bytes().decode("utf-8")


class FakeVisionAdapter:
    name = "fake-vision"
    configured = True

    def analyze(self, image_path: Path, prompt: str) -> str:
        return f"saw {image_path.read_bytes().decode('utf-8')}"


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
                "write_files": Permission("write_files", "write files", PermissionDecision.PROMPT),
                "access_network": Permission(
                    "access_network", "network", PermissionDecision.PROMPT
                ),
                "generate_images": Permission(
                    "generate_images", "generate images", PermissionDecision.PROMPT
                ),
            }
        )
        self.permission_manager = permission_manager
        self.event_bus = EventBus()
        audit_logger = AuditLogger(base / "audit.log")
        self.memory = MemoryManager(base / "jarvis.db")
        bot_manager = BotManager(permission_manager, audit_logger, event_bus=self.event_bus)
        bot_manager.register(CodeBot(permission_manager, audit_logger))
        bot_manager.register(FileBot(permission_manager, audit_logger, self_root=base / "self"))
        bot_manager.register(SystemBot(permission_manager, audit_logger))
        self.image_manager = ImageManager(
            adapter=StubImageAdapter(),
            output_dir=base / "images",
            event_bus=self.event_bus,
        )
        bot_manager.register(ImageBot(permission_manager, audit_logger, self.image_manager))
        self.core = JarvisCore(
            memory=self.memory,
            bot_manager=bot_manager,
            lm_provider=EchoLMProvider(),
            audit_logger=audit_logger,
            event_bus=self.event_bus,
        )
        self.settings = SettingsStore(base / "settings.json")
        self.recovery = RecoveryManager(
            base / "jarvis.db",
            base / "backups",
            NullVectorStore(),
            encryption_key="test-backup-key",
        )
        self.backup_scheduler = BackupScheduler(self.recovery, self.event_bus)
        self.voice = VoiceManager(event_bus=self.event_bus)
        self.vision = VisionManager(event_bus=self.event_bus)

        class StubWakeListener:
            def __init__(self) -> None:
                self.started = False

            def start(self) -> None:
                self.started = True

            def stop(self) -> None:
                self.started = False

        self.wake_listener = StubWakeListener()
        self.safety_switch = SafetySwitch(self.settings, event_bus=self.event_bus)
        self.heartbeat = HeartbeatEngine(
            self.memory,
            self.core.lm_provider,
            IdentityManager(self.memory, self.event_bus),
            MemoryConsolidator(
                self.memory, self.core.lm_provider, self.settings, self.event_bus, enabled=False
            ),
            self.settings,
            safety_switch=self.safety_switch,
            event_bus=self.event_bus,
            enabled=False,
        )
        app = create_app()
        app.dependency_overrides[get_core] = lambda: self.core
        app.dependency_overrides[get_safety_switch] = lambda: self.safety_switch
        app.dependency_overrides[get_heartbeat_engine] = lambda: self.heartbeat
        self.improvements = ImprovementManager(
            self.memory,
            self.settings,
            self.core.lm_provider,
            safety_switch=self.safety_switch,
            event_bus=self.event_bus,
        )
        app.dependency_overrides[get_improvement_manager] = lambda: self.improvements
        app.dependency_overrides[get_event_bus] = lambda: self.event_bus
        app.dependency_overrides[get_permission_manager] = lambda: self.permission_manager
        app.dependency_overrides[get_recovery_manager] = lambda: self.recovery
        app.dependency_overrides[get_backup_scheduler] = lambda: self.backup_scheduler
        app.dependency_overrides[get_settings_store] = lambda: self.settings
        app.dependency_overrides[get_wake_word_listener] = lambda: self.wake_listener
        app.dependency_overrides[get_system_monitor] = lambda: SystemMonitor()
        app.dependency_overrides[get_voice_manager] = lambda: self.voice
        app.dependency_overrides[get_vision_manager] = lambda: self.vision
        app.dependency_overrides[get_image_manager] = lambda: self.image_manager
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

    def test_image_status_endpoint_reports_adapter(self) -> None:
        response = self.client.get("/api/v1/image/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["adapter"], "stub")
        self.assertTrue(body["configured"])
        self.assertFalse(body["network"])

    def test_image_generate_requires_permission_then_serves_file(self) -> None:
        # First call is gated (generate_images defaults to prompt) -> 403.
        gated = self.client.post("/api/v1/image/generate", json={"prompt": "a red bicycle"})
        self.assertEqual(gated.status_code, 403)

        self.permission_manager.update_decisions({"generate_images": "allowed"})
        generated = self.client.post(
            "/api/v1/image/generate", json={"prompt": "a red bicycle"}
        )
        self.assertEqual(generated.status_code, 200)
        body = generated.json()
        self.assertTrue(body["image_url"].startswith("/api/v1/image/file/"))

        served = self.client.get(body["image_url"])
        self.assertEqual(served.status_code, 200)
        self.assertTrue(served.content)

    def test_research_agent_fire_and_poll(self) -> None:
        import time

        bot_manager = self.core.bot_manager
        bot_manager.register(FakeResearchBot(self.permission_manager, bot_manager.audit_logger))
        agent = DeepResearchAgent(
            lm_provider=ScriptedLMProvider(),
            bot_manager=bot_manager,
            memory=self.memory,
            audit_logger=bot_manager.audit_logger,
            event_bus=self.event_bus,
        )
        self.client.app.dependency_overrides[get_agent_manager] = lambda: agent

        # POST returns immediately with a run id (202), not the finished report.
        start = self.client.post(
            "/api/v1/agent/research",
            json={"goal": "what is odysseus", "username": "agent-user"},
        )
        self.assertEqual(start.status_code, 202)
        run_id = start.json()["run_id"]
        self.assertEqual(start.json()["status"], "running")

        # Poll the status endpoint until the background run finishes.
        body = None
        for _ in range(200):
            poll = self.client.get(f"/api/v1/agent/research/{run_id}")
            self.assertEqual(poll.status_code, 200)
            body = poll.json()
            if body["status"] != "running":
                break
            time.sleep(0.02)

        self.assertEqual(body["status"], "complete")
        self.assertIn("Grounded report", body["report"])
        self.assertEqual(len(body["sources"]), 2)
        self.assertTrue(body["steps"])
        self.assertTrue(body["task_id"])
        # access_network defaulted to prompt, yet the run left no pending approval:
        # the agent's scope carried it through unattended.
        self.assertEqual(self.permission_manager.pending_requests(), [])

    def test_research_agent_unknown_run_404(self) -> None:
        response = self.client.get("/api/v1/agent/research/does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_image_file_rejects_path_traversal(self) -> None:
        response = self.client.get("/api/v1/image/file/..%2f..%2fsettings.json")
        self.assertEqual(response.status_code, 404)

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

    def test_task_endpoint_updates_status_and_description(self) -> None:
        created = self.client.post(
            "/api/v1/tasks",
            json={"username": "api-user", "name": "Ship scaffold", "description": "baseline"},
        )

        updated = self.client.patch(
            f"/api/v1/tasks/{created.json()['task_id']}",
            json={
                "username": "api-user",
                "description": "notes updated",
                "status": "in_progress",
            },
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["description"], "notes updated")
        self.assertEqual(updated.json()["status"], "in_progress")

    def test_task_update_rejects_wrong_user(self) -> None:
        created = self.client.post(
            "/api/v1/tasks",
            json={"username": "owner-user", "name": "Private task"},
        )

        response = self.client.patch(
            f"/api/v1/tasks/{created.json()['task_id']}",
            json={"username": "other-user", "status": "complete"},
        )

        self.assertEqual(response.status_code, 404)

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

    def test_prompt_permission_can_be_resolved_and_retried_once(self) -> None:
        sample = Path(self.tmp.name) / "sample.py"
        sample.write_text("print('ready')\n", encoding="utf-8")
        first = self.client.post(
            "/api/v1/bot/code/exec",
            json={"action": "analyze", "payload": {"path": str(sample)}, "sender": "api-user"},
        )

        self.assertFalse(first.json()["ok"])
        request = first.json()["payload"]["permission_request"]
        listed = self.client.get("/api/v1/permissions/requests")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["request_id"], request["request_id"])

        resolved = self.client.post(
            f"/api/v1/permissions/requests/{request['request_id']}/resolve",
            json={"decision": "allowed"},
        )
        next_attempt = self.client.post(
            "/api/v1/bot/code/exec",
            json={"action": "analyze", "payload": {"path": str(sample)}, "sender": "api-user"},
        )

        self.assertEqual(resolved.status_code, 200)
        self.assertTrue(resolved.json()["result"]["ok"])
        self.assertFalse(next_attempt.json()["ok"])
        self.assertIn("permission_request", next_attempt.json()["payload"])

    def test_external_file_write_executes_after_approval(self) -> None:
        target = Path(self.tmp.name) / "user-files" / "approved.txt"
        requested = self.client.post(
            "/api/v1/bot/file/exec",
            json={
                "action": "write",
                "payload": {"path": str(target), "content": "approved\n"},
                "sender": "api-user",
            },
        )

        self.assertFalse(requested.json()["ok"])
        request_id = requested.json()["payload"]["permission_request"]["request_id"]
        resolved = self.client.post(
            f"/api/v1/permissions/requests/{request_id}/resolve",
            json={"decision": "allowed"},
        )

        self.assertTrue(resolved.json()["result"]["ok"])
        self.assertEqual(target.read_text(encoding="utf-8"), "approved\n")

    def test_settings_wake_word_toggle_starts_and_stops_listener(self) -> None:
        enabled = self.client.put("/api/v1/settings", json={"wake_word": True})
        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["wake_word"])
        self.assertTrue(self.wake_listener.started)

        disabled = self.client.put("/api/v1/settings", json={"wake_word": False})
        self.assertFalse(disabled.json()["wake_word"])
        self.assertFalse(self.wake_listener.started)

    def test_settings_turbo_round_trip_masks_api_key(self) -> None:
        update = self.client.put(
            "/api/v1/settings",
            json={"turbo_mode": True, "gemini_api_key": "secret-key"},
        )

        self.assertEqual(update.status_code, 200)
        body = update.json()
        self.assertTrue(body["turbo_mode"])
        self.assertTrue(body["gemini_api_key_set"])
        self.assertNotIn("gemini_api_key", body)
        self.assertEqual(self.settings.read()["gemini_api_key"], "secret-key")

        cleared = self.client.put("/api/v1/settings", json={"gemini_api_key": ""})
        self.assertFalse(cleared.json()["gemini_api_key_set"])

    def test_settings_round_trip(self) -> None:
        updated = self.client.put("/api/v1/settings", json={"theme": "dark"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["theme"], "dark")

        fetched = self.client.get("/api/v1/settings")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["theme"], "dark")

    def test_settings_include_manifest_permissions(self) -> None:
        response = self.client.get("/api/v1/settings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["permissions"]["execute_scripts"], "denied")
        self.assertEqual(response.json()["permissions"]["read_files"], "prompt")

    def test_settings_permission_update_affects_bot_execution(self) -> None:
        updated = self.client.put(
            "/api/v1/settings",
            json={"permissions": {"execute_scripts": "allowed"}},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["permissions"]["execute_scripts"], "allowed")

        response = self.client.post(
            "/api/v1/bot/system/exec",
            json={"action": "execute", "payload": {"text": "date"}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_settings_reject_unknown_permission(self) -> None:
        response = self.client.put(
            "/api/v1/settings",
            json={"permissions": {"unknown_permission": "allowed"}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown permission", response.json()["detail"])

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

    def test_local_frontend_cors_allows_task_patch(self) -> None:
        response = self.client.options(
            "/api/v1/tasks/1",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("PATCH", response.headers["access-control-allow-methods"])

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

    def test_reflection_endpoint_creates_searchable_summary(self) -> None:
        created = self.client.post(
            "/api/v1/chat",
            json={"message": "remember the copper key", "username": "reflect-user"},
        )

        response = self.client.post(
            f"/api/v1/conversations/{created.json()['conversation_id']}/reflections",
            json={"username": "reflect-user"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("I heard", response.json()["summary"])
        user = self.memory.get_or_create_user("reflect-user")
        documents = self.memory.query_documents(user.user_id, "Summarize", 5)
        self.assertEqual(documents[0].source, f"conversation:{created.json()['conversation_id']}")

    def test_memory_consolidate_endpoint_runs_and_reports(self) -> None:
        from jarvis.backend.core.app_factory import get_memory_consolidator
        from jarvis.backend.core.memory_consolidator import MemoryConsolidator

        class FactProvider(EchoLMProvider):
            async def generate(self, text, context, metadata=None, history=None):
                if "extract durable facts" in text.lower():
                    return "- The user tests O.D.I.N. daily"
                return "The user tests O.D.I.N. daily."

        self.client.post(
            "/api/v1/chat",
            json={"message": "I test O.D.I.N. every day", "username": "local-user"},
        )
        consolidator = MemoryConsolidator(
            self.memory, FactProvider(), self.settings, self.event_bus
        )
        self.client.app.dependency_overrides[get_memory_consolidator] = lambda: consolidator

        response = self.client.post("/api/v1/memory/consolidate")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["facts_saved"], 1)
        self.assertFalse(body["skipped"])

    def test_memory_blocks_round_trip(self) -> None:
        initial = self.client.get("/api/v1/memory/blocks")
        self.assertEqual(initial.status_code, 200)
        self.assertIn("persona", initial.json()["blocks"])

        updated = self.client.put(
            "/api/v1/memory/blocks/human",
            json={"content": "Zeb is building O.D.I.N."},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["blocks"]["human"], "Zeb is building O.D.I.N.")

        rejected = self.client.put("/api/v1/memory/blocks/bogus", json={"content": "x"})
        self.assertEqual(rejected.status_code, 400)

    def test_memory_status_reports_vector_provider(self) -> None:
        response = self.client.get("/api/v1/memory/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["vector"]["provider"], "null")

    def test_startup_health_reports_core_services(self) -> None:
        response = self.client.get("/api/v1/health/startup")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertIn("memory", response.json()["services"])

    def test_data_management_endpoints_export_and_delete(self) -> None:
        created = self.client.post(
            "/api/v1/chat",
            json={"message": "export this", "username": "data-user"},
        ).json()
        exported = self.client.get(
            f"/api/v1/conversations/{created['conversation_id']}/export",
            params={"username": "data-user"},
        )
        deleted = self.client.delete(
            f"/api/v1/conversations/{created['conversation_id']}",
            params={"username": "data-user"},
        )

        self.assertEqual(exported.status_code, 200)
        self.assertEqual(len(exported.json()["messages"]), 2)
        self.assertTrue(deleted.json()["deleted"])

    def test_model_load_endpoint_updates_loaded_model(self) -> None:
        response = self.client.post("/api/v1/models/load", json={"model_name": "echo-alt"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["models"][0]["id"], "echo-alt")
        self.assertTrue(body["models"][0]["loaded"])
        self.assertEqual(body["provider"]["provider"], "builtin")
        self.assertEqual(self.settings.read()["model_name"], "echo-alt")

    def test_system_overview_returns_metrics_and_live_nodes(self) -> None:
        self.client.post(
            "/api/v1/tasks",
            json={"name": "calibrate sensors", "username": "local-user"},
        )

        response = self.client.get("/api/v1/system/overview")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["metrics"]["cpu_percent"], 0.0)
        self.assertGreater(body["metrics"]["memory"]["total_bytes"], 0)
        self.assertIn("network", body["metrics"])
        nodes = body["nodes"]
        self.assertTrue(nodes["reasoning_engine"]["ok"])
        self.assertEqual(nodes["automation_hub"]["tasks_total"], 1)
        self.assertEqual(nodes["security_mesh"]["pending_approvals"], 0)
        self.assertIn("voice_interface", nodes)

    def test_emergency_stop_endpoints_round_trip(self) -> None:
        status = self.client.get("/api/v1/system/safety").json()
        self.assertFalse(status["engaged"])

        # A bare POST with no body must still halt (panic button).
        engaged = self.client.post("/api/v1/system/emergency-stop").json()
        self.assertTrue(engaged["engaged"])
        self.assertIn("system", engaged["blocked_bots"])

        overview = self.client.get("/api/v1/system/overview").json()
        self.assertFalse(overview["nodes"]["security_mesh"]["ok"])
        self.assertTrue(overview["nodes"]["security_mesh"]["emergency_stop"])

        released = self.client.post("/api/v1/system/resume").json()
        self.assertFalse(released["engaged"])

    def test_emergency_stop_accepts_reason(self) -> None:
        engaged = self.client.post(
            "/api/v1/system/emergency-stop", json={"reason": "fire drill"}
        ).json()
        self.assertEqual(engaged["reason"], "fire drill")
        self.client.post("/api/v1/system/resume")

    def test_heartbeat_tick_endpoint_advances_and_status_reflects(self) -> None:
        status = self.client.get("/api/v1/heartbeat").json()
        self.assertEqual(status["tick_count"], 0)

        ticked = self.client.post("/api/v1/heartbeat/tick").json()
        self.assertFalse(ticked["skipped"])
        self.assertEqual(ticked["tick"], 1)

        after = self.client.get("/api/v1/heartbeat").json()
        self.assertEqual(after["tick_count"], 1)

        overview = self.client.get("/api/v1/system/overview").json()
        self.assertEqual(overview["nodes"]["continuity_engine"]["tick_count"], 1)

    def test_heartbeat_tick_skipped_while_halted(self) -> None:
        self.client.post("/api/v1/system/emergency-stop")
        ticked = self.client.post("/api/v1/heartbeat/tick").json()
        self.assertTrue(ticked["skipped"])
        self.client.post("/api/v1/system/resume")

    def test_goals_endpoints_round_trip(self) -> None:
        created = self.client.post(
            "/api/v1/goals", json={"text": "finish the project", "username": "local-user"}
        ).json()
        self.assertEqual(created["status"], "active")
        goal_id = created["goal_id"]

        active = self.client.get("/api/v1/goals?status=active").json()
        self.assertEqual(len(active), 1)

        updated = self.client.patch(
            f"/api/v1/goals/{goal_id}", json={"status": "done"}
        ).json()
        self.assertEqual(updated["status"], "done")
        self.assertEqual(self.client.get("/api/v1/goals?status=active").json(), [])

    def test_update_unknown_goal_returns_404(self) -> None:
        response = self.client.patch("/api/v1/goals/999", json={"status": "done"})
        self.assertEqual(response.status_code, 404)

    def test_improvement_propose_approve_apply_revert_flow(self) -> None:
        created = self.client.post(
            "/api/v1/improvements",
            json={
                "kind": "memory",
                "target": "persona",
                "proposed_value": "Odin: terse and kind.",
                "rationale": "tighten the voice",
            },
        ).json()
        self.assertEqual(created["status"], "pending")
        pid = created["proposal_id"]

        # Cannot apply before approval.
        self.assertEqual(
            self.client.post(f"/api/v1/improvements/{pid}/apply").status_code, 409
        )

        self.client.post(f"/api/v1/improvements/{pid}/approve")
        applied = self.client.post(f"/api/v1/improvements/{pid}/apply").json()
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(
            self.client.get("/api/v1/memory/blocks").json()["blocks"]["persona"],
            "Odin: terse and kind.",
        )

        reverted = self.client.post(f"/api/v1/improvements/{pid}/revert").json()
        self.assertEqual(reverted["status"], "reverted")

    def test_improvement_apply_blocked_while_halted(self) -> None:
        created = self.client.post(
            "/api/v1/improvements",
            json={"kind": "memory", "target": "persona", "proposed_value": "x"},
        ).json()
        pid = created["proposal_id"]
        self.client.post(f"/api/v1/improvements/{pid}/approve")
        self.client.post("/api/v1/system/emergency-stop")
        self.assertEqual(
            self.client.post(f"/api/v1/improvements/{pid}/apply").status_code, 409
        )
        self.client.post("/api/v1/system/resume")

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

    def test_voice_status_reports_adapter_state(self) -> None:
        response = self.client.get("/api/v1/voice/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "idle")
        self.assertFalse(body["stt_configured"])
        self.assertFalse(body["tts_configured"])

    def test_vision_status_reports_unconfigured_adapter(self) -> None:
        response = self.client.get("/api/v1/vision/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "idle")
        self.assertFalse(body["configured"])
        self.assertEqual(body["adapter"], "unconfigured")

    def test_vision_analyze_reports_unconfigured_adapter(self) -> None:
        response = self.client.post(
            "/api/v1/vision/analyze",
            json={"image_base64": base64.b64encode(b"frame").decode("ascii")},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("Vision adapter is not configured", response.json()["detail"])

    def test_vision_analyzes_uploaded_image(self) -> None:
        self.vision.adapter = FakeVisionAdapter()

        response = self.client.post(
            "/api/v1/vision/analyze",
            json={
                "image_base64": base64.b64encode(b"a smiling face").decode("ascii"),
                "image_suffix": ".jpg",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["description"], "saw a smiling face")

    def test_vision_analyze_rejects_invalid_base64(self) -> None:
        self.vision.adapter = FakeVisionAdapter()

        response = self.client.post(
            "/api/v1/vision/analyze",
            json={"image_base64": "not valid base64!!!"},
        )

        self.assertEqual(response.status_code, 400)

    def test_voice_synthesize_reports_unconfigured_adapter(self) -> None:
        response = self.client.post(
            "/api/v1/voice/synthesize",
            json={"text": "hello"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("Text-to-speech adapter is not configured", response.json()["detail"])

    def test_voice_transcribes_uploaded_audio(self) -> None:
        self.voice.stt_adapter = FakeSpeechToTextAdapter()

        response = self.client.post(
            "/api/v1/voice/transcribe",
            json={
                "audio_base64": base64.b64encode(b"uploaded transcript").decode("ascii"),
                "audio_suffix": ".webm",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcript"], "uploaded transcript")

    def test_voice_setup_downloads_local_whisper_model(self) -> None:
        model_path = Path(self.tmp.name) / "models" / "ggml-base.en.bin"
        self.voice.stt_adapter = WhisperCliSpeechToTextAdapter(
            "whisper-cli",
            model_path,
            "ffmpeg",
        )

        class Download:
            def __init__(self):
                self.remaining = [b"x" * 1_000_001, b""]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return None

            def read(self, size):
                return self.remaining.pop(0)

        with patch("urllib.request.urlopen", return_value=Download()):
            response = self.client.post("/api/v1/voice/setup")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["configured"])
        self.assertTrue(model_path.is_file())

    def test_voice_state_update_emits_websocket_event(self) -> None:
        with self.client.websocket_connect("/api/v1/events") as websocket:
            response = self.client.post("/api/v1/voice/state", json={"state": "listening"})
            self.assertEqual(response.status_code, 200)
            event = websocket.receive_json()

        self.assertEqual(event["type"], "voice.state")
        self.assertEqual(event["payload"]["state"], "listening")

    def test_recovery_integrity_reports_sqlite_health(self) -> None:
        self.memory.get_or_create_user("health-user")

        response = self.client.get("/api/v1/recovery/integrity")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["sqlite_ok"])

    def test_recovery_schedule_reports_daily_four_am(self) -> None:
        response = self.client.get("/api/v1/recovery/schedule")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])
        self.assertEqual(response.json()["hour"], 4)
        self.assertEqual(response.json()["retention"], 30)

    def test_recovery_backup_missing_database_returns_404(self) -> None:
        missing = Path(self.tmp.name) / "missing.db"
        app = self.client.app
        app.dependency_overrides[get_recovery_manager] = lambda: RecoveryManager(
            missing,
            Path(self.tmp.name) / "backups",
            NullVectorStore(),
            encryption_key="test-backup-key",
        )

        response = self.client.post("/api/v1/recovery/backups")

        self.assertEqual(response.status_code, 404)
        app.dependency_overrides[get_recovery_manager] = lambda: self.recovery

    def test_recovery_backup_is_encrypted_and_can_restore(self) -> None:
        self.memory.get_or_create_user("before-backup")
        created = self.client.post("/api/v1/recovery/backups")

        self.assertEqual(created.status_code, 200)
        snapshot = created.json()
        encrypted = Path(snapshot["path"]).read_bytes()
        self.assertTrue(snapshot["encrypted"])
        self.assertNotIn(b"SQLite format 3", encrypted)

        self.memory.get_or_create_user("after-backup")
        restored = self.client.post(
            "/api/v1/recovery/restore",
            json={"filename": snapshot["filename"]},
        )

        self.assertEqual(restored.status_code, 200)
        with closing(sqlite3.connect(self.recovery.db_path)) as connection:
            usernames = {
                row[0] for row in connection.execute("SELECT username FROM users").fetchall()
            }
        self.assertIn("before-backup", usernames)
        self.assertNotIn("after-backup", usernames)
        self.assertTrue(Path(restored.json()["safety_backup"]).is_file())

    def test_recovery_restore_rejects_tampered_backup(self) -> None:
        self.memory.get_or_create_user("backup-user")
        created = self.client.post("/api/v1/recovery/backups").json()
        backup_path = Path(created["path"])
        encrypted = bytearray(backup_path.read_bytes())
        encrypted[-1] ^= 1
        backup_path.write_bytes(encrypted)

        response = self.client.post(
            "/api/v1/recovery/restore",
            json={"filename": created["filename"]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("authentication failed", response.json()["detail"])

    def test_recovery_restore_recreates_missing_database(self) -> None:
        self.memory.get_or_create_user("backup-user")
        created = self.client.post("/api/v1/recovery/backups").json()
        self.recovery.db_path.unlink()

        response = self.client.post(
            "/api/v1/recovery/restore",
            json={"filename": created["filename"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["safety_backup"])
        self.assertTrue(self.recovery.db_path.is_file())

    def test_recovery_restore_rejects_path_traversal(self) -> None:
        response = self.client.post(
            "/api/v1/recovery/restore",
            json={"filename": "../jarvis.db"},
        )

        self.assertEqual(response.status_code, 404)


def _auth_app(token: str | None) -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/ping")
    def ping() -> dict[str, bool]:
        return {"pong": True}

    @app.websocket("/api/v1/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"ok": True})
        await websocket.close()

    app.add_middleware(TokenAuthMiddleware, token=token)
    return app


class AuthMiddlewareTests(unittest.TestCase):
    def test_disabled_passes_through(self) -> None:
        client = TestClient(_auth_app(None))
        self.assertEqual(client.get("/api/v1/ping").status_code, 200)

    def test_enabled_blocks_without_token(self) -> None:
        client = TestClient(_auth_app("s3cret"))
        self.assertEqual(client.get("/api/v1/ping").status_code, 401)

    def test_enabled_allows_bearer_and_header(self) -> None:
        client = TestClient(_auth_app("s3cret"))
        self.assertEqual(
            client.get("/api/v1/ping", headers={"Authorization": "Bearer s3cret"}).status_code,
            200,
        )
        self.assertEqual(
            client.get("/api/v1/ping", headers={"X-Odin-Token": "s3cret"}).status_code,
            200,
        )
        self.assertEqual(
            client.get("/api/v1/ping", headers={"Authorization": "Bearer wrong"}).status_code,
            401,
        )

    def test_healthz_and_options_exempt(self) -> None:
        client = TestClient(_auth_app("s3cret"))
        self.assertEqual(client.get("/healthz").status_code, 200)
        # OPTIONS preflight must not be blocked by auth (CORS handles it).
        self.assertNotEqual(client.options("/api/v1/ping").status_code, 401)

    def test_http_get_allows_query_param_token(self) -> None:
        # Browser-loaded media (<img>/<audio> src, download fetch) can't set the
        # Authorization header, so a plain GET must authenticate via ?token=.
        # This is the contract the frontend's resolveMediaUrl relies on.
        client = TestClient(_auth_app("s3cret"))
        self.assertEqual(client.get("/api/v1/ping?token=s3cret").status_code, 200)
        self.assertEqual(client.get("/api/v1/ping?token=wrong").status_code, 401)

    def test_websocket_requires_token_query_param(self) -> None:
        client = TestClient(_auth_app("s3cret"))
        with client.websocket_connect("/api/v1/ws?token=s3cret") as websocket:
            self.assertEqual(websocket.receive_json(), {"ok": True})
        with self.assertRaises(Exception):
            with client.websocket_connect("/api/v1/ws"):
                pass

    def test_resolve_token_off_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_REQUIRE_AUTH", None)
            self.assertFalse(auth_required())
            self.assertIsNone(resolve_api_token())

    def test_resolve_token_uses_env_when_enabled(self) -> None:
        with patch.dict(
            os.environ,
            {"JARVIS_REQUIRE_AUTH": "1", "JARVIS_API_TOKEN": "from-env"},
            clear=False,
        ):
            self.assertTrue(auth_required())
            self.assertEqual(resolve_api_token(), "from-env")

    def test_resolve_token_generates_key_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "api.key"
            with patch.dict(
                os.environ,
                {"JARVIS_REQUIRE_AUTH": "yes", "JARVIS_API_TOKEN_PATH": str(key_path)},
                clear=False,
            ):
                os.environ.pop("JARVIS_API_TOKEN", None)
                token = resolve_api_token()
            self.assertTrue(token)
            self.assertEqual(key_path.read_text(encoding="utf-8").strip(), token)


if __name__ == "__main__":
    unittest.main()
