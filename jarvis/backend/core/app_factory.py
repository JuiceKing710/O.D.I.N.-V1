from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.bots.file_bot import FileBot
from jarvis.backend.bots.research_bot import ResearchBot
from jarvis.backend.bots.system_bot import SystemBot
from jarvis.backend.core.bot_manager import BotManager
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import EchoLMProvider, OllamaProvider
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.recovery_manager import RecoveryManager
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.core.vector_store import ChromaVectorStore, NullVectorStore, VectorStoreInterface
from jarvis.backend.core.voice_manager import (
    CommandTextToSpeechAdapter,
    MacOSTextToSpeechAdapter,
    UnconfiguredSpeechToTextAdapter,
    UnconfiguredTextToSpeechAdapter,
    VoiceManager,
    WhisperCommandSpeechToTextAdapter,
)
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import PermissionManager


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _default_db_path() -> Path:
    return Path(os.environ.get("JARVIS_DB_PATH", "data/jarvis.db"))


def _ollama_timeout_seconds() -> float:
    raw = os.environ.get("OLLAMA_TIMEOUT_SECONDS", "120")
    try:
        return float(raw)
    except ValueError:
        return 120.0


@lru_cache(maxsize=1)
def get_permission_manager() -> PermissionManager:
    return PermissionManager.from_manifest(PACKAGE_ROOT / "config" / "permissions.json")


@lru_cache(maxsize=1)
def get_settings_store() -> SettingsStore:
    return SettingsStore(Path(os.environ.get("JARVIS_SETTINGS_PATH", "data/settings.json")))


@lru_cache(maxsize=1)
def get_event_bus() -> EventBus:
    return EventBus()


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStoreInterface:
    chroma_path = os.environ.get("JARVIS_CHROMA_PATH")
    if not chroma_path:
        return NullVectorStore()
    try:
        return ChromaVectorStore(chroma_path)
    except RuntimeError:
        return NullVectorStore()


@lru_cache(maxsize=1)
def get_recovery_manager() -> RecoveryManager:
    return RecoveryManager(
        db_path=_default_db_path(),
        backup_dir=Path(os.environ.get("JARVIS_BACKUP_DIR", "data/backups")),
        vector_store=get_vector_store(),
        encryption_key=os.environ.get("JARVIS_BACKUP_KEY"),
    )


@lru_cache(maxsize=1)
def get_voice_manager() -> VoiceManager:
    voice_output_dir = Path(os.environ.get("JARVIS_VOICE_OUTPUT_DIR", "data/voice"))
    stt_command = os.environ.get("JARVIS_WHISPER_COMMAND")
    tts_command = os.environ.get("JARVIS_TTS_COMMAND")
    stt_adapter = (
        WhisperCommandSpeechToTextAdapter(stt_command)
        if stt_command
        else UnconfiguredSpeechToTextAdapter()
    )
    if tts_command:
        tts_adapter = CommandTextToSpeechAdapter(tts_command, voice_output_dir)
    elif MacOSTextToSpeechAdapter.available():
        tts_adapter = MacOSTextToSpeechAdapter(voice_output_dir)
    else:
        tts_adapter = UnconfiguredTextToSpeechAdapter()
    return VoiceManager(
        stt_adapter=stt_adapter,
        tts_adapter=tts_adapter,
        event_bus=get_event_bus(),
    )


@lru_cache(maxsize=1)
def get_core() -> JarvisCore:
    permission_manager = get_permission_manager()
    audit_logger = AuditLogger(Path(os.environ.get("JARVIS_AUDIT_LOG", "data/audit.log")))
    event_bus = get_event_bus()
    memory = MemoryManager(_default_db_path(), vector_store=get_vector_store())
    bot_manager = BotManager(
        permission_manager=permission_manager,
        audit_logger=audit_logger,
        event_bus=event_bus,
    )
    bot_manager.register(FileBot(permission_manager, audit_logger))
    bot_manager.register(ResearchBot(permission_manager, audit_logger))
    bot_manager.register(CodeBot(permission_manager, audit_logger))
    bot_manager.register(SystemBot(permission_manager, audit_logger))

    if os.environ.get("JARVIS_LLM_PROVIDER") == "echo":
        lm_provider = EchoLMProvider()
    else:
        lm_provider = OllamaProvider(
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            model=os.environ.get("OLLAMA_MODEL"),
            timeout_seconds=_ollama_timeout_seconds(),
        )
    return JarvisCore(
        memory=memory,
        bot_manager=bot_manager,
        lm_provider=lm_provider,
        audit_logger=audit_logger,
        event_bus=event_bus,
    )
