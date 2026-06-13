from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
import urllib.error
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse
from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.bots.file_bot import FileBot
from jarvis.backend.bots.research_bot import ResearchBot
from jarvis.backend.bots.system_bot import SystemBot
from jarvis.backend.core.app_factory import _ollama_timeout_seconds, _persisted_model_name
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.core.backup_scheduler import BackupScheduler
from jarvis.backend.core.bot_manager import BotManager, BotMessage
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import (
    EchoLMProvider,
    GeminiProvider,
    OllamaProvider,
    TurboSwitchProvider,
)
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.recovery_manager import RecoveryManager
from jarvis.backend.core.vector_store import InMemoryVectorStore, NullVectorStore, VectorStoreInterface
from jarvis.backend.core.voice_manager import (
    InterruptionConfig,
    MacOSTextToSpeechAdapter,
    WhisperCliSpeechToTextAdapter,
    VoiceManager,
    VoiceState,
)
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import (
    Permission,
    PermissionApprovalRequired,
    PermissionDecision,
    PermissionManager,
)
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

    def delete(self, collection: str, record_id: str) -> None:
        raise RuntimeError("vector delete failed")

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


class MockHttpResponse:
    def __init__(self, body: dict[str, Any] | str) -> None:
        self.body = (
            body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
        )

    def __enter__(self) -> "MockHttpResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeStreamResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self) -> "FakeStreamResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def __iter__(self):
        return iter(self.lines)


class FakeSpeechToTextAdapter:
    name = "fake-stt"
    configured = True

    def transcribe(self, audio_path: Path) -> str:
        return audio_path.read_bytes().decode("utf-8")


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
                "write_files": Permission("write_files", "write files", PermissionDecision.PROMPT),
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

    def _build_core(self, provider, event_bus=None) -> JarvisCore:
        return JarvisCore(
            memory=self.memory,
            bot_manager=self.bot_manager,
            lm_provider=provider,
            audit_logger=self.audit,
            event_bus=event_bus,
        )

    def test_handle_message_persists_conversation(self) -> None:
        result = asyncio.run(self.core.handle_message("remember the blue folder", "tester"))
        self.assertEqual(result["conversation_id"], 1)
        user = self.memory.get_or_create_user("tester")
        matches = self.memory.query_messages(user.user_id, "blue", limit=10)
        self.assertEqual(len(matches), 2)

    def test_bot_command_dispatches_registered_bot(self) -> None:
        path = Path(self.tmp.name) / "sample.py"
        path.write_text("def ready():\n    return True\n", encoding="utf-8")
        self.permissions.update_decisions({"read_files": "allowed"})

        result = asyncio.run(self.core.handle_message(f"/code analyze {path}", "tester"))

        self.assertEqual(result["bot"], "code")
        self.assertIn("Analyzed", result["reply"])

    def test_natural_language_request_dispatches_allowlisted_bot_action(self) -> None:
        path = Path(self.tmp.name) / "natural.py"
        path.write_text("def ready():\n    return True\n", encoding="utf-8")
        self.permissions.update_decisions({"read_files": "allowed"})

        result = asyncio.run(self.core.handle_message(f"analyze code {path}", "tester"))

        self.assertEqual(result["bot"], "code")
        self.assertIn("Analyzed", result["reply"])

    def test_code_bot_returns_real_file_analysis(self) -> None:
        path = Path(self.tmp.name) / "sample.py"
        path.write_text("class Ready:\n    pass\n\n# TODO ship\n", encoding="utf-8")
        self.permissions.update_decisions({"read_files": "allowed"})
        bot = CodeBot(self.permissions, self.audit)

        response = asyncio.run(
            bot.on_request(
                BotRequest(sender="test", action="analyze", payload={"path": str(path)}, correlation_id="1")
            )
        )

        self.assertTrue(response.ok)
        self.assertEqual(response.payload["analysis"]["class_count"], 1)
        self.assertEqual(response.payload["analysis"]["todo_count"], 1)

    def test_system_bot_executes_approved_command(self) -> None:
        self.permissions.update_decisions({"execute_scripts": "allowed"})
        bot = SystemBot(self.permissions, self.audit)

        response = asyncio.run(
            bot.on_request(
                BotRequest(
                    sender="test",
                    action="execute",
                    payload={"text": "printf hello"},
                    correlation_id="1",
                )
            )
        )

        self.assertTrue(response.ok)
        self.assertEqual(response.payload["stdout"], "hello")

    def test_file_bot_writes_self_files_without_approval(self) -> None:
        self_root = Path(self.tmp.name) / "jarvis-self"
        target = self_root / "notes" / "ready.txt"
        bot = FileBot(self.permissions, self.audit, self_root=self_root)

        response = asyncio.run(
            bot.on_request(
                BotRequest(
                    sender="test",
                    action="write",
                    payload={"path": str(target), "content": "ready\n"},
                    correlation_id="1",
                )
            )
        )

        self.assertTrue(response.ok)
        self.assertTrue(response.payload["self_file"])
        self.assertEqual(target.read_text(encoding="utf-8"), "ready\n")

    def test_file_bot_requires_approval_for_user_files(self) -> None:
        self_root = Path(self.tmp.name) / "jarvis-self"
        target = Path(self.tmp.name) / "user-files" / "notes.txt"
        bot = FileBot(self.permissions, self.audit, self_root=self_root)
        request = BotRequest(
            sender="test",
            action="write",
            payload={"path": str(target), "content": "approved\n"},
            correlation_id="1",
        )

        pending = asyncio.run(bot.on_request(request))
        request_id = pending.payload["permission_request"]["request_id"]
        self.permissions.resolve_request(request_id, PermissionDecision.ALLOWED)
        approved = asyncio.run(bot.on_request(request))

        self.assertFalse(pending.ok)
        self.assertTrue(approved.ok)
        self.assertFalse(approved.payload["self_file"])
        self.assertEqual(target.read_text(encoding="utf-8"), "approved\n")

    def test_research_bot_returns_network_results(self) -> None:
        self.permissions.update_decisions({"access_network": "allowed"})
        bot = ResearchBot(self.permissions, self.audit)
        body = '<a class="result__a" href="https://example.com">Example result</a>'

        with patch("urllib.request.urlopen", return_value=MockHttpResponse(body)):
            response = asyncio.run(
                bot.on_request(
                    BotRequest(
                        sender="test",
                        action="search",
                        payload={"text": "example"},
                        correlation_id="1",
                    )
                )
            )

        self.assertTrue(response.ok)
        self.assertEqual(response.payload["results"][0]["url"], "https://example.com")

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

    def test_prompt_permission_can_be_approved_once(self) -> None:
        with self.assertRaises(PermissionApprovalRequired) as pending:
            self.permissions.require_allowed(
                "read_files",
                actor="tester",
                reason="Read file: sample.py",
            )

        self.permissions.resolve_request(pending.exception.request.request_id, PermissionDecision.ALLOWED)
        self.permissions.require_allowed(
            "read_files",
            actor="tester",
            reason="Read file: sample.py",
        )

        with self.assertRaises(PermissionApprovalRequired):
            self.permissions.require_allowed(
                "read_files",
                actor="tester",
                reason="Read file: sample.py",
            )

    def test_pending_permission_requests_survive_restart_without_grants(self) -> None:
        storage = Path(self.tmp.name) / "permissions.json"
        permissions = {
            "read_files": Permission("read_files", "read files", PermissionDecision.PROMPT)
        }
        first = PermissionManager(permissions, storage_path=storage)
        with self.assertRaises(PermissionApprovalRequired):
            first.require_allowed("read_files", actor="tester", reason="Read file: sample.py")

        restarted = PermissionManager(permissions, storage_path=storage)

        self.assertEqual(len(restarted.pending_requests()), 1)
        request = restarted.pending_requests()[0]
        restarted.resolve_request(request.request_id, PermissionDecision.ALLOWED)
        restarted.require_allowed("read_files", actor="tester", reason="Read file: sample.py")
        with self.assertRaises(PermissionApprovalRequired):
            restarted.require_allowed("read_files", actor="tester", reason="Read file: sample.py")

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

    def test_database_schema_has_explicit_version(self) -> None:
        with sqlite3.connect(self.memory.db_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(version, 2)

    def test_full_backup_bundle_restores_settings_audit_and_vector_files(self) -> None:
        base = Path(self.tmp.name) / "bundle"
        db_path = base / "jarvis.db"
        settings_path = base / "settings.json"
        audit_path = base / "audit.log"
        vector_path = base / "chroma"
        MemoryManager(db_path).get_or_create_user("bundle-user")
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text('{"theme":"dark"}', encoding="utf-8")
        audit_path.write_text('{"action":"before"}\n', encoding="utf-8")
        vector_path.mkdir()
        (vector_path / "index.bin").write_bytes(b"vector-before")
        recovery = RecoveryManager(
            db_path,
            base / "backups",
            NullVectorStore(),
            encryption_key="bundle-key",
            settings_path=settings_path,
            audit_log_path=audit_path,
            vector_path=vector_path,
        )
        snapshot = recovery.create_sqlite_backup()
        settings_path.write_text('{"theme":"light"}', encoding="utf-8")
        audit_path.write_text('{"action":"after"}\n', encoding="utf-8")
        (vector_path / "index.bin").write_bytes(b"vector-after")

        recovery.restore_sqlite_backup(snapshot.path.name)

        self.assertEqual(settings_path.read_text(encoding="utf-8"), '{"theme":"dark"}')
        self.assertIn("before", audit_path.read_text(encoding="utf-8"))
        self.assertEqual((vector_path / "index.bin").read_bytes(), b"vector-before")

    def test_backup_restore_rejects_bundle_checksum_failure(self) -> None:
        base = Path(self.tmp.name) / "checksum"
        db_path = base / "jarvis.db"
        MemoryManager(db_path)
        recovery = RecoveryManager(
            db_path,
            base / "backups",
            NullVectorStore(),
            encryption_key="bundle-key",
        )
        snapshot = recovery.create_sqlite_backup()
        archive = base / "tampered.zip"
        archive.write_bytes(recovery._decrypt(snapshot.path.read_bytes()))
        tampered = base / "tampered-rebuilt.zip"
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, "w") as target:
            for name in source.namelist():
                content = b"tampered" if name == "database/jarvis.db" else source.read(name)
                target.writestr(name, content)
        snapshot.path.write_bytes(recovery._encrypt(tampered.read_bytes()))

        with self.assertRaisesRegex(ValueError, "checksum failed"):
            recovery.restore_sqlite_backup(snapshot.path.name)

    def test_backup_restore_rolls_back_database_after_optional_file_failure(self) -> None:
        base = Path(self.tmp.name) / "rollback"
        db_path = base / "jarvis.db"
        memory = MemoryManager(db_path)
        memory.get_or_create_user("before")
        recovery = RecoveryManager(
            db_path,
            base / "backups",
            NullVectorStore(),
            encryption_key="bundle-key",
        )
        snapshot = recovery.create_sqlite_backup()
        memory.get_or_create_user("current")

        with patch.object(recovery, "_restore_optional_bundle_files", side_effect=OSError("failed")):
            with self.assertRaisesRegex(OSError, "failed"):
                recovery.restore_sqlite_backup(snapshot.path.name)

        with sqlite3.connect(db_path) as connection:
            users = {row[0] for row in connection.execute("SELECT username FROM users")}
        self.assertIn("current", users)

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
        context = self.memory.query_context(user.user_id, "Summarize", limit=5)
        self.assertTrue(any("[conversation:" in item for item in context))

    def test_voice_transcribes_uploaded_audio(self) -> None:
        voice = VoiceManager(stt_adapter=FakeSpeechToTextAdapter())

        transcript = voice.transcribe_audio(b"hello from audio", ".webm")

        self.assertEqual(transcript, "hello from audio")
        self.assertEqual(voice.state, VoiceState.IDLE)

    def test_vision_analyzes_uploaded_image(self) -> None:
        from jarvis.backend.core.vision_manager import VisionManager, VisionState

        class FakeVisionAdapter:
            name = "fake-vision"
            configured = True

            def analyze(self, image_path, prompt):
                return f"{prompt[:4]}::{image_path.read_bytes().decode('utf-8')}"

        vision = VisionManager(adapter=FakeVisionAdapter())

        description = vision.analyze_image(b"a face", ".jpg", prompt="Describe it")

        self.assertEqual(description, "Desc::a face")
        self.assertEqual(vision.state, VisionState.IDLE)

    def test_vision_unconfigured_adapter_raises_and_resets_state(self) -> None:
        from jarvis.backend.core.vision_manager import VisionManager, VisionState

        vision = VisionManager()

        with self.assertRaises(RuntimeError):
            vision.analyze_image(b"frame", ".jpg")
        self.assertEqual(vision.state, VisionState.IDLE)
        self.assertFalse(vision.status().configured)

    def test_whisper_cli_converts_audio_and_returns_transcript(self) -> None:
        audio = Path(self.tmp.name) / "input.webm"
        model = Path(self.tmp.name) / "model.bin"
        audio.write_bytes(b"audio")
        model.write_bytes(b"model" + b"\0" * 1_000_000)
        adapter = WhisperCliSpeechToTextAdapter("whisper-cli", model, "ffmpeg")

        def fake_run(command, **kwargs):
            if command[0] == "ffmpeg":
                Path(command[-1]).write_bytes(b"wav")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="hello from whisper", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            transcript = adapter.transcribe(audio)

        self.assertEqual(transcript, "hello from whisper")

    def test_wake_word_listener_publishes_through_bound_loop(self) -> None:
        from jarvis.backend.core.event_bus import EventBus
        from jarvis.backend.core.wake_word import WakeWordListener

        bus = EventBus()
        listener = WakeWordListener(bus, model_name="hey_jarvis")

        async def fire():
            listener.bind_loop(asyncio.get_running_loop())
            listener._publish(0.91)
            await asyncio.sleep(0)

        asyncio.run(fire())

        events = [event for event in bus.history() if event.type == "voice.wake"]
        self.assertEqual(events, [])  # transient events stay out of history

        async def fire_and_collect():
            listener.bind_loop(asyncio.get_running_loop())
            queue = await bus.subscribe()
            listener._publish(0.91)
            await asyncio.sleep(0)
            return queue.get_nowait()

        event = asyncio.run(fire_and_collect())
        self.assertEqual(event.type, "voice.wake")
        self.assertEqual(event.payload["model"], "hey_jarvis")

    def test_piper_adapter_synthesizes_through_stdin(self) -> None:
        from jarvis.backend.core.voice_manager import PiperTextToSpeechAdapter

        output_dir = Path(self.tmp.name) / "voice"
        adapter = PiperTextToSpeechAdapter("/fake/piper", "/fake/model.onnx", output_dir)
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["input"] = kwargs.get("input")
            Path(command[command.index("-f") + 1]).write_bytes(b"RIFFfake")
            return SimpleNamespace(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = adapter.synthesize("Greetings from Asgard.")

        self.assertEqual(result.suffix, ".wav")
        self.assertEqual(captured["input"], "Greetings from Asgard.")
        self.assertEqual(captured["command"][0], "/fake/piper")
        self.assertIn("/fake/model.onnx", captured["command"])

        self.assertFalse(
            PiperTextToSpeechAdapter.available(None, Path("/fake/model.onnx"))
        )
        self.assertFalse(
            PiperTextToSpeechAdapter.available("/fake/piper", Path("/missing.onnx"))
        )

    def test_macos_voice_output_is_converted_to_wav(self) -> None:
        output_dir = Path(self.tmp.name) / "voice"
        adapter = MacOSTextToSpeechAdapter(output_dir)

        def fake_run(command, **kwargs):
            output_path = Path(command[2] if command[0] == "say" else command[-1])
            output_path.write_bytes(command[0].encode("utf-8"))
            return SimpleNamespace(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = adapter.synthesize("hello")

        self.assertEqual(result.suffix, ".wav")
        self.assertEqual(result.read_bytes(), b"afconvert")
        self.assertFalse(any(output_dir.glob("*.aiff")))

    def test_ollama_provider_parses_models_and_selects_first(self) -> None:
        provider = OllamaProvider()

        with patch(
            "urllib.request.urlopen",
            return_value=MockHttpResponse(
                {"models": [{"name": "llama3.2:latest"}, {"name": "mistral:latest"}]}
            ),
        ):
            models = asyncio.run(provider.list_models())
            status = asyncio.run(provider.status())

        self.assertEqual(models[0].id, "llama3.2:latest")
        self.assertTrue(models[0].loaded)
        self.assertEqual(status.selected_model, "llama3.2:latest")
        self.assertTrue(status.available)

    def test_ollama_provider_skips_embedding_models_when_auto_selecting(self) -> None:
        provider = OllamaProvider()

        with patch(
            "urllib.request.urlopen",
            return_value=MockHttpResponse(
                {"models": [{"name": "nomic-embed-text:latest"}, {"name": "llama3.1:8b"}]}
            ),
        ):
            status = asyncio.run(provider.status())

        self.assertEqual(status.selected_model, "llama3.1:8b")
        self.assertTrue(status.available)

    def test_ollama_provider_honors_configured_model(self) -> None:
        provider = OllamaProvider(model="mistral:latest")

        with patch(
            "urllib.request.urlopen",
            return_value=MockHttpResponse(
                {"models": [{"name": "llama3.2:latest"}, {"name": "mistral:latest"}]}
            ),
        ):
            models = asyncio.run(provider.list_models())

        loaded = [model for model in models if model.loaded]
        self.assertEqual(loaded[0].id, "mistral:latest")

    def test_ollama_provider_reports_unreachable_server(self) -> None:
        provider = OllamaProvider()

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaisesRegex(RuntimeError, "ollama serve"):
                asyncio.run(provider.generate("hello", []))

    def test_ollama_provider_reports_no_models(self) -> None:
        provider = OllamaProvider()

        with patch("urllib.request.urlopen", return_value=MockHttpResponse({"models": []})):
            with self.assertRaisesRegex(RuntimeError, "ollama pull"):
                asyncio.run(provider.generate("hello", []))

    def test_ollama_provider_reports_missing_configured_model(self) -> None:
        provider = OllamaProvider(model="missing:latest")

        with patch(
            "urllib.request.urlopen",
            return_value=MockHttpResponse({"models": [{"name": "llama3.2:latest"}]}),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing:latest"):
                asyncio.run(provider.generate("hello", []))

    def test_ollama_provider_sends_chat_payload_with_context(self) -> None:
        provider = OllamaProvider()
        seen_payloads = []

        def fake_urlopen(request, timeout):
            if request.full_url.endswith("/api/tags"):
                return MockHttpResponse({"models": [{"name": "llama3.2:latest"}]})
            seen_payloads.append(json.loads(request.data.decode("utf-8")))
            return MockHttpResponse({"message": {"content": "Hello. I am Jarvis."}})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            reply = asyncio.run(provider.generate("hello", ["user likes concise answers"]))

        self.assertEqual(reply, "Hello. I am Jarvis.")
        payload = seen_payloads[0]
        self.assertEqual(payload["model"], "llama3.2:latest")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("O.D.I.N.", payload["messages"][0]["content"])
        self.assertIn("memory context", payload["messages"][1]["content"])
        self.assertEqual(payload["messages"][-1]["content"], "hello")

    def test_ollama_timeout_env_falls_back_when_invalid(self) -> None:
        with patch.dict("os.environ", {"OLLAMA_TIMEOUT_SECONDS": "not-a-number"}):
            self.assertEqual(_ollama_timeout_seconds(), 120.0)

    def test_system_monitor_snapshot_reports_host_metrics(self) -> None:
        from jarvis.backend.core.system_monitor import SystemMonitor

        monitor = SystemMonitor()
        first = monitor.snapshot()
        second = monitor.snapshot()

        self.assertGreaterEqual(first["cpu_percent"], 0.0)
        self.assertGreater(first["memory"]["total_bytes"], 0)
        self.assertGreater(first["disk"]["total_bytes"], 0)
        self.assertGreater(first["uptime_seconds"], 0)
        self.assertGreaterEqual(second["network"]["sent_bytes_per_sec"], 0.0)
        self.assertGreaterEqual(second["network"]["recv_bytes_per_sec"], 0.0)
        self.assertIn("sampled_at", second)

    def test_transient_events_reach_subscribers_but_not_history(self) -> None:
        from jarvis.backend.core.event_bus import EventBus

        bus = EventBus()
        queue = asyncio.run(bus.subscribe())
        bus.publish("system.metrics", {"cpu_percent": 1.0}, transient=True)
        bus.publish("chat.message", {"text": "hello"})

        history_types = [event.type for event in bus.history()]
        self.assertEqual(history_types, ["chat.message"])
        self.assertEqual(queue.get_nowait().type, "system.metrics")
        self.assertEqual(queue.get_nowait().type, "chat.message")

    def test_handle_message_sends_conversation_history_to_provider(self) -> None:
        captured = {}

        class RecordingProvider(EchoLMProvider):
            async def generate_stream(self, text, context, metadata=None, history=None):
                captured["history"] = history
                yield f"echo: {text}"

        core = self._build_core(RecordingProvider())
        first = asyncio.run(core.handle_message("my favorite rune is Othala", "zeb"))
        asyncio.run(
            core.handle_message(
                "what is my favorite rune?", "zeb", conversation_id=first["conversation_id"]
            )
        )

        history = captured["history"]
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "my favorite rune is Othala")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertIn("echo: my favorite rune is Othala", history[1]["content"])

    def test_handle_message_publishes_stream_deltas_transiently(self) -> None:
        from jarvis.backend.core.event_bus import EventBus

        class ChunkProvider(EchoLMProvider):
            async def generate_stream(self, text, context, metadata=None, history=None):
                yield "All "
                yield "systems "
                yield "nominal."

        bus = EventBus()
        core = self._build_core(ChunkProvider(), event_bus=bus)
        result = asyncio.run(core.handle_message("status report", "zeb"))

        self.assertEqual(result["reply"], "All systems nominal.")
        history_types = [event.type for event in bus.history()]
        self.assertNotIn("chat.stream", history_types)
        self.assertIn("chat.message", history_types)

    def test_ollama_messages_include_history_turns(self) -> None:
        messages = OllamaProvider._build_messages(
            "and now?",
            [],
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Your name is Odin", messages[0]["content"])
        self.assertEqual(
            [(m["role"], m["content"]) for m in messages[1:]],
            [("user", "hello"), ("assistant", "hi there"), ("user", "and now?")],
        )

    def test_gemini_payload_maps_history_to_model_role(self) -> None:
        payload = GeminiProvider._build_payload(
            "and now?",
            ["a fact"],
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
        )

        self.assertIn("Your name is Odin", payload["system_instruction"]["parts"][0]["text"])
        self.assertIn("a fact", payload["system_instruction"]["parts"][0]["text"])
        roles = [item["role"] for item in payload["contents"]]
        self.assertEqual(roles, ["user", "model", "user"])

    def test_ollama_stream_yields_deltas_until_done(self) -> None:
        provider = OllamaProvider(model="llama3.1:8b")
        lines = [
            b'{"message": {"content": "Hel"}, "done": false}\n',
            b'{"message": {"content": "lo."}, "done": true}\n',
        ]

        def fake_urlopen(request, timeout=None):
            if request.full_url.endswith("/api/tags"):
                return MockHttpResponse({"models": [{"name": "llama3.1:8b"}]})
            return FakeStreamResponse(lines)

        async def collect():
            chunks = []
            async for delta in provider.generate_stream("hi", []):
                chunks.append(delta)
            return chunks

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            chunks = asyncio.run(collect())

        self.assertEqual(chunks, ["Hel", "lo."])

    def test_turbo_stream_falls_back_to_local_when_gemini_fails(self) -> None:
        import urllib.error

        local = EchoLMProvider()
        settings = {"turbo_mode": True, "gemini_api_key": "test-key"}
        provider = TurboSwitchProvider(local, lambda: settings)

        async def collect():
            chunks = []
            async for delta in provider.generate_stream("offline hello", []):
                chunks.append(delta)
            return "".join(chunks)

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("no internet"),
        ):
            reply = asyncio.run(collect())

        self.assertIn("offline hello", reply)
        self.assertIn("no internet", provider.last_turbo_error)

    def test_gemini_provider_parses_reply_and_sends_key_header(self) -> None:
        provider = GeminiProvider(api_key="test-key")
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return MockHttpResponse(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "Greetings from the cloud."}]}}
                    ]
                }
            )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            reply = asyncio.run(provider.generate("hello", ["fact one"]))

        self.assertEqual(reply, "Greetings from the cloud.")
        self.assertIn("gemini-2.5-flash:generateContent", captured["url"])
        self.assertEqual(captured["headers"].get("X-goog-api-key"), "test-key")
        self.assertIn("Odin", captured["payload"]["system_instruction"]["parts"][0]["text"])
        self.assertIn("fact one", captured["payload"]["system_instruction"]["parts"][0]["text"])

    def test_turbo_switch_uses_gemini_when_enabled_and_falls_back_offline(self) -> None:
        local = EchoLMProvider()
        settings = {"turbo_mode": True, "gemini_api_key": "test-key"}
        provider = TurboSwitchProvider(local, lambda: settings)

        with patch(
            "urllib.request.urlopen",
            return_value=MockHttpResponse(
                {"candidates": [{"content": {"parts": [{"text": "turbo reply"}]}}]}
            ),
        ):
            reply = asyncio.run(provider.generate("hello", []))
            status = asyncio.run(provider.status())

        self.assertEqual(reply, "turbo reply")
        self.assertEqual(status.provider, "gemini (turbo)")

        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("no internet"),
        ):
            offline_reply = asyncio.run(provider.generate("hello offline", []))

        self.assertIn("hello offline", offline_reply)
        self.assertIn("no internet", provider.last_turbo_error)

        settings["turbo_mode"] = False
        local_status = asyncio.run(provider.status())
        self.assertEqual(local_status.provider, "builtin")

    def test_memory_consolidation_extracts_facts_and_updates_profile(self) -> None:
        from jarvis.backend.core.event_bus import EventBus
        from jarvis.backend.core.memory_consolidator import MemoryConsolidator
        from jarvis.backend.core.settings_store import SettingsStore

        class ConsolidatingProvider(EchoLMProvider):
            async def generate(self, text, context, metadata=None, history=None):
                if "extract durable facts" in text.lower():
                    return "- Zeb rides a black Yamaha MT-07\n- Zeb is building O.D.I.N.\nNOTHING"
                if "merge" in text.lower():
                    return "Zeb rides a black Yamaha MT-07 and is building O.D.I.N."
                return "ok"

        user = self.memory.get_or_create_user("zeb")
        convo = self.memory.create_conversation(user.user_id, title="bikes")
        self.memory.add_message(convo.convo_id, "user", "my bike is a black Yamaha MT-07")
        self.memory.add_message(convo.convo_id, "assistant", "Noted.")

        bus = EventBus()
        settings = SettingsStore(Path(self.tmp.name) / "consolidator-settings.json")
        consolidator = MemoryConsolidator(
            self.memory, ConsolidatingProvider(), settings, bus
        )
        result = asyncio.run(consolidator.consolidate("zeb"))

        self.assertEqual(result["facts_saved"], 2)
        self.assertTrue(result["profile_updated"])
        documents = self.memory.list_documents(user.user_id)
        self.assertEqual(len(documents), 2)
        self.assertTrue(all(doc.source.startswith("consolidated:") for doc in documents))
        self.assertIn("Yamaha", self.memory.get_memory_blocks()["human"])
        self.assertIn("memory.consolidated", [event.type for event in bus.history()])
        self.assertTrue(settings.read()["last_consolidation_at"])

        second = asyncio.run(consolidator.consolidate("zeb"))
        self.assertTrue(second["skipped"])

    def test_memory_blocks_default_update_and_reach_the_prompt(self) -> None:
        blocks = self.memory.get_memory_blocks()
        self.assertIn("persona", blocks)
        self.assertEqual(blocks["human"], "")

        self.memory.update_memory_block("human", "Zeb rides a black Yamaha MT-07.")
        with self.assertRaises(ValueError):
            self.memory.update_memory_block("unknown", "nope")

        captured = {}

        class RecordingProvider(EchoLMProvider):
            async def generate_stream(self, text, context, metadata=None, history=None):
                captured["context"] = context
                yield "ok"

        core = self._build_core(RecordingProvider())
        asyncio.run(core.handle_message("hello there", "zeb"))

        joined = "\n".join(captured["context"])
        self.assertIn("[Odin persona]", joined)
        self.assertIn("[About the user] Zeb rides a black Yamaha MT-07.", joined)

    def test_sqlite_vector_store_recalls_by_meaning_not_keywords(self) -> None:
        from jarvis.backend.core.vector_store import SqliteVectorStore

        vocabulary = {
            "motorcycle": [1.0, 0.0, 0.0],
            "bike": [0.96, 0.1, 0.0],
            "weather": [0.0, 1.0, 0.0],
            "groceries": [0.0, 0.0, 1.0],
        }

        def fake_embedder(text: str) -> list[float]:
            for word, vector in vocabulary.items():
                if word in text.lower():
                    return vector
            return [0.1, 0.1, 0.1]

        store = SqliteVectorStore(Path(self.tmp.name) / "vectors.db", embedder=fake_embedder)
        store.upsert_message(1, "my motorcycle is a black Yamaha", {"convo": 1})
        store.upsert_message(2, "the weather is cloudy today", {"convo": 1})
        store.upsert_message(3, "buy groceries on Sunday", {"convo": 2})

        results = store.query("messages", "what bike do I ride?", limit=2)

        self.assertEqual(results[0].record_id, "message:1")
        self.assertIn("Yamaha", results[0].content)
        self.assertGreater(results[0].score, results[1].score)

        store.delete("messages", "message:1")
        self.assertNotIn(
            "message:1",
            [row.record_id for row in store.query("messages", "motorcycle", limit=5)],
        )
        health = store.health()
        self.assertEqual(health["provider"], "sqlite-local")
        self.assertEqual(health["collections"], {"messages": 2})

    def test_sqlite_vector_store_degrades_gracefully_without_embedder(self) -> None:
        from jarvis.backend.core.vector_store import SqliteVectorStore

        def broken_embedder(text: str) -> list[float]:
            raise RuntimeError("Embedding request failed: Ollama is down")

        store = SqliteVectorStore(Path(self.tmp.name) / "vectors.db", embedder=broken_embedder)

        self.assertIsNone(store.upsert_message(1, "hello world", {}))
        self.assertEqual(store.query("messages", "hello", limit=3), [])
        self.assertIn("Ollama is down", store.health()["last_error"])

    def test_persisted_model_name_ignores_default_and_blank_values(self) -> None:
        store = SettingsStore(Path(self.tmp.name) / "model-settings.json")
        self.assertIsNone(_persisted_model_name(store))

        store.update({"model_name": "   "})
        self.assertIsNone(_persisted_model_name(store))

        store.update({"model_name": "llama3.1:8b"})
        self.assertEqual(_persisted_model_name(store), "llama3.1:8b")

    def test_backup_scheduler_targets_next_local_four_am(self) -> None:
        recovery = RecoveryManager(
            Path(self.tmp.name) / "scheduler.db",
            Path(self.tmp.name) / "backups",
            NullVectorStore(),
            encryption_key="test-key",
        )
        scheduler = BackupScheduler(recovery, hour=4)
        before = datetime.now().astimezone().replace(hour=3, minute=30, second=0, microsecond=0)
        after = before.replace(hour=5)

        self.assertEqual(scheduler.next_run(before).date(), before.date())
        self.assertEqual(scheduler.next_run(before).hour, 4)
        self.assertEqual(scheduler.next_run(after).date(), after.date() + timedelta(days=1))

    def test_backup_scheduler_catches_up_after_four_am(self) -> None:
        db_path = Path(self.tmp.name) / "catch-up.db"
        MemoryManager(db_path)
        recovery = RecoveryManager(
            db_path,
            Path(self.tmp.name) / "backups",
            NullVectorStore(),
            encryption_key="test-key",
        )
        scheduler = BackupScheduler(recovery, hour=4)
        after_four = datetime.now().astimezone().replace(hour=5, minute=0, second=0, microsecond=0)

        self.assertTrue(scheduler.needs_catch_up(after_four))
        asyncio.run(scheduler.run_backup())
        self.assertFalse(scheduler.needs_catch_up(after_four))


if __name__ == "__main__":
    unittest.main()
