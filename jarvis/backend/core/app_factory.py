from __future__ import annotations

import os
import secrets
import shutil
import sys
import threading
from functools import lru_cache
from pathlib import Path

from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.bots.file_bot import FileBot
from jarvis.backend.bots.research_bot import ResearchBot
from jarvis.backend.bots.system_bot import SystemBot
from jarvis.backend.core.backup_scheduler import BackupScheduler
from jarvis.backend.core.bot_manager import BotManager
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import EchoLMProvider, OllamaProvider, TurboSwitchProvider
from jarvis.backend.core.memory_consolidator import MemoryConsolidator
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.recovery_manager import RecoveryManager
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.core.system_monitor import SystemMonitor
from jarvis.backend.core.vector_store import (
    ChromaVectorStore,
    NullVectorStore,
    OllamaEmbedder,
    SqliteVectorStore,
    VectorStoreInterface,
)
from jarvis.backend.core.vision_manager import (
    CommandVisionAdapter,
    GeminiVisionAdapter,
    OllamaVisionAdapter,
    UnconfiguredVisionAdapter,
    VisionManager,
)
from jarvis.backend.core.wake_word import WakeWordListener
from jarvis.backend.core.voice_manager import (
    CommandTextToSpeechAdapter,
    MacOSTextToSpeechAdapter,
    PiperTextToSpeechAdapter,
    UnconfiguredSpeechToTextAdapter,
    UnconfiguredTextToSpeechAdapter,
    VoiceManager,
    WhisperCommandSpeechToTextAdapter,
    WhisperCliSpeechToTextAdapter,
)
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import PermissionManager


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _default_db_path() -> Path:
    return Path(os.environ.get("JARVIS_DB_PATH", "data/jarvis.db"))


def _persisted_model_name(settings_store: SettingsStore) -> str | None:
    saved = settings_store.read().get("model_name")
    if isinstance(saved, str):
        cleaned = saved.strip()
        if cleaned and cleaned != "local-default":
            return cleaned
    return None


def _ollama_timeout_seconds() -> float:
    raw = os.environ.get("OLLAMA_TIMEOUT_SECONDS", "120")
    try:
        return float(raw)
    except ValueError:
        return 120.0


def _venv_binary(name: str) -> str | None:
    candidate = Path(sys.executable).parent / name
    return str(candidate) if candidate.is_file() else None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _backup_key() -> str:
    configured = os.environ.get("JARVIS_BACKUP_KEY")
    if configured:
        return configured
    key_path = Path(os.environ.get("JARVIS_BACKUP_KEY_PATH", "data/backup.key"))
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        key_path.chmod(0o600)
    return key_path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def get_permission_manager() -> PermissionManager:
    return PermissionManager.from_manifest(
        PACKAGE_ROOT / "config" / "permissions.json",
        storage_path=Path(os.environ.get("JARVIS_PERMISSION_REQUESTS_PATH", "data/permissions.json")),
    )


@lru_cache(maxsize=1)
def get_settings_store() -> SettingsStore:
    return SettingsStore(Path(os.environ.get("JARVIS_SETTINGS_PATH", "data/settings.json")))


@lru_cache(maxsize=1)
def get_event_bus() -> EventBus:
    return EventBus()


@lru_cache(maxsize=1)
def get_wake_word_listener() -> WakeWordListener:
    try:
        threshold = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.5"))
    except ValueError:
        threshold = 0.5
    return WakeWordListener(
        get_event_bus(),
        model_name=os.environ.get("JARVIS_WAKE_MODEL", "hey_jarvis"),
        threshold=threshold,
    )


@lru_cache(maxsize=1)
def get_memory_consolidator() -> MemoryConsolidator:
    core = get_core()
    return MemoryConsolidator(
        core.memory,
        core.lm_provider,
        get_settings_store(),
        get_event_bus(),
        hour=_env_int("JARVIS_CONSOLIDATION_HOUR", 4),
        enabled=os.environ.get("JARVIS_CONSOLIDATION", "enabled").lower() != "disabled",
    )


@lru_cache(maxsize=1)
def get_system_monitor() -> SystemMonitor:
    try:
        interval = float(os.environ.get("JARVIS_METRICS_INTERVAL_SECONDS", "2"))
    except ValueError:
        interval = 2.0
    return SystemMonitor(get_event_bus(), interval_seconds=max(interval, 0.5))


@lru_cache(maxsize=1)
def get_audit_logger() -> AuditLogger:
    return AuditLogger(Path(os.environ.get("JARVIS_AUDIT_LOG", "data/audit.log")))


@lru_cache(maxsize=1)
def get_db_lock() -> threading.RLock:
    return threading.RLock()


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStoreInterface:
    provider = os.environ.get("JARVIS_VECTOR_PROVIDER", "local").strip().lower()
    if provider == "disabled":
        return NullVectorStore()
    chroma_path = os.environ.get("JARVIS_CHROMA_PATH")
    if chroma_path:
        try:
            return ChromaVectorStore(chroma_path)
        except RuntimeError:
            return NullVectorStore()
    embedder = OllamaEmbedder(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        model=os.environ.get("JARVIS_EMBED_MODEL", "nomic-embed-text"),
    )
    vector_db = Path(os.environ.get("JARVIS_VECTOR_DB_PATH", "data/vectors.db"))
    return SqliteVectorStore(vector_db, embedder=embedder)


@lru_cache(maxsize=1)
def get_recovery_manager() -> RecoveryManager:
    vector_path = os.environ.get("JARVIS_CHROMA_PATH")
    return RecoveryManager(
        db_path=_default_db_path(),
        backup_dir=Path(os.environ.get("JARVIS_BACKUP_DIR", "data/backups")),
        vector_store=get_vector_store(),
        encryption_key=_backup_key(),
        db_lock=get_db_lock(),
        settings_path=Path(os.environ.get("JARVIS_SETTINGS_PATH", "data/settings.json")),
        audit_log_path=Path(os.environ.get("JARVIS_AUDIT_LOG", "data/audit.log")),
        vector_path=Path(vector_path) if vector_path else None,
    )


@lru_cache(maxsize=1)
def get_backup_scheduler() -> BackupScheduler:
    return BackupScheduler(
        get_recovery_manager(),
        get_event_bus(),
        enabled=os.environ.get("JARVIS_SCHEDULED_BACKUPS", "enabled").lower()
        not in {"0", "false", "disabled"},
        hour=_env_int("JARVIS_BACKUP_HOUR", 4),
        retention=_env_int("JARVIS_BACKUP_RETENTION", 30),
    )


@lru_cache(maxsize=1)
def get_voice_manager() -> VoiceManager:
    voice_output_dir = Path(os.environ.get("JARVIS_VOICE_OUTPUT_DIR", "data/voice"))
    stt_command = os.environ.get("JARVIS_WHISPER_COMMAND")
    tts_command = os.environ.get("JARVIS_TTS_COMMAND")
    whisper_cli = shutil.which("whisper-cli")
    ffmpeg = shutil.which("ffmpeg")
    whisper_model = Path(
        os.environ.get(
            "JARVIS_WHISPER_MODEL",
            str(Path.home() / "jarvis-models" / "ggml-base.en.bin"),
        )
    )
    if stt_command:
        stt_adapter = WhisperCommandSpeechToTextAdapter(stt_command)
    elif whisper_cli and ffmpeg:
        stt_adapter = WhisperCliSpeechToTextAdapter(whisper_cli, whisper_model, ffmpeg)
    else:
        stt_adapter = UnconfiguredSpeechToTextAdapter()
    piper_binary = shutil.which("piper") or _venv_binary("piper")
    piper_model = Path(
        os.environ.get(
            "JARVIS_PIPER_VOICE",
            str(Path.home() / "jarvis-models" / "piper" / "en_US-ryan-medium.onnx"),
        )
    )
    if tts_command:
        tts_adapter = CommandTextToSpeechAdapter(tts_command, voice_output_dir)
    elif PiperTextToSpeechAdapter.available(piper_binary, piper_model):
        tts_adapter = PiperTextToSpeechAdapter(piper_binary, piper_model, voice_output_dir)
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
def get_vision_manager() -> VisionManager:
    vision_command = os.environ.get("JARVIS_VISION_COMMAND")
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    settings = get_settings_store().read()
    gemini_key = str(settings.get("gemini_api_key") or "").strip()
    # Local-first: prefer the on-device Ollama vision model so camera frames
    # never leave the machine and stay fast on modest hardware. moondream (~1.6 GB)
    # is the default because it runs comfortably offline on an 8 GB Mac; a heavier
    # model like llava is used only if moondream is not installed. Fall back to
    # Gemini just when no local model is present and turbo mode is enabled.
    preferred = os.environ.get("JARVIS_VISION_MODEL")
    candidates = [preferred] if preferred else ["moondream", "llava"]
    local_model = next(
        (m for m in candidates if m and OllamaVisionAdapter.available(ollama_base_url, m)),
        None,
    )
    if vision_command:
        adapter = CommandVisionAdapter(vision_command)
    elif local_model:
        adapter = OllamaVisionAdapter(model=local_model, base_url=ollama_base_url)
    elif settings.get("turbo_mode") and gemini_key:
        adapter = GeminiVisionAdapter(
            api_key=gemini_key,
            model=os.environ.get("JARVIS_VISION_GEMINI_MODEL", "gemini-2.5-flash"),
        )
    else:
        adapter = UnconfiguredVisionAdapter()
    return VisionManager(adapter=adapter, event_bus=get_event_bus())


@lru_cache(maxsize=1)
def get_core() -> JarvisCore:
    permission_manager = get_permission_manager()
    audit_logger = get_audit_logger()
    event_bus = get_event_bus()
    memory = MemoryManager(
        _default_db_path(),
        vector_store=get_vector_store(),
        db_lock=get_db_lock(),
    )
    bot_manager = BotManager(
        permission_manager=permission_manager,
        audit_logger=audit_logger,
        event_bus=event_bus,
    )
    bot_manager.register(
        FileBot(
            permission_manager,
            audit_logger,
            self_root=Path(os.environ.get("JARVIS_SELF_ROOT", PACKAGE_ROOT.parent)),
        )
    )
    bot_manager.register(ResearchBot(permission_manager, audit_logger))
    bot_manager.register(CodeBot(permission_manager, audit_logger))
    bot_manager.register(SystemBot(permission_manager, audit_logger))

    if os.environ.get("JARVIS_LLM_PROVIDER") == "echo":
        local_provider: EchoLMProvider | OllamaProvider = EchoLMProvider()
    else:
        local_provider = OllamaProvider(
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            model=os.environ.get("OLLAMA_MODEL") or _persisted_model_name(get_settings_store()),
            timeout_seconds=_ollama_timeout_seconds(),
        )
    lm_provider = TurboSwitchProvider(
        local_provider,
        get_settings_store().read,
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
    )
    return JarvisCore(
        memory=memory,
        bot_manager=bot_manager,
        lm_provider=lm_provider,
        audit_logger=audit_logger,
        event_bus=event_bus,
    )
