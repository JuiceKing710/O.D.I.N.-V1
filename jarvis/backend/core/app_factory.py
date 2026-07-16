from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import threading
from functools import lru_cache
from pathlib import Path

from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.core.agent_manager import DeepResearchAgent
from jarvis.backend.bots.desktop_bot import DesktopBot
from jarvis.backend.bots.file_bot import FileBot
from jarvis.backend.bots.image_bot import ImageBot
from jarvis.backend.bots.research_bot import ResearchBot
from jarvis.backend.bots.system_bot import SystemBot
from jarvis.backend.core.backup_scheduler import BackupScheduler
from jarvis.backend.core.bot_manager import BotManager
from jarvis.backend.core.camera_monitor import CameraMonitor
from jarvis.backend.core.camera_source import (
    CameraSource,
    RTSPCameraSource,
    UnconfiguredCameraSource,
)
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.notifier import NtfyNotifier, Notifier, UnconfiguredNotifier
from jarvis.backend.core.file_snapshot import FileSnapshotStore
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import EchoLMProvider, OllamaProvider, TurboSwitchProvider
from jarvis.backend.core.heartbeat import HeartbeatEngine
from jarvis.backend.core.identity_manager import IdentityManager
from jarvis.backend.core.improvement_manager import ImprovementManager
from jarvis.backend.core.memory_consolidator import MemoryConsolidator
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.recovery_manager import RecoveryManager
from jarvis.backend.core.safety_switch import SafetySwitch
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.core.skill_manager import SkillManager
from jarvis.backend.core.system_monitor import SystemMonitor
from jarvis.backend.core.vector_store import (
    ChromaVectorStore,
    NullVectorStore,
    OllamaEmbedder,
    SqliteVectorStore,
    VectorStoreInterface,
)
from jarvis.backend.core.image_manager import (
    CommandImageAdapter,
    GeminiImageAdapter,
    ImageManager,
    UnconfiguredImageAdapter,
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
def get_safety_switch() -> SafetySwitch:
    return SafetySwitch(
        get_settings_store(),
        event_bus=get_event_bus(),
        audit_logger=get_audit_logger(),
    )


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
    # Model resolution priority: explicit env path, then the model picked in
    # Settings (a bare filename inside the models dir), then the small default.
    models_dir = Path(
        os.environ.get("JARVIS_WHISPER_MODEL_DIR", str(Path.home() / "jarvis-models"))
    )
    settings_model = Path(
        str(get_settings_store().read().get("whisper_model") or "").strip()
    ).name
    whisper_model = Path(
        os.environ.get("JARVIS_WHISPER_MODEL")
        or str(models_dir / (settings_model or "ggml-base.en.bin"))
    )
    whisper_gpu = os.environ.get("JARVIS_WHISPER_GPU", "enabled").lower() not in {
        "0",
        "false",
        "disabled",
    }
    if stt_command:
        stt_adapter = WhisperCommandSpeechToTextAdapter(stt_command)
    elif whisper_cli and ffmpeg:
        stt_adapter = WhisperCliSpeechToTextAdapter(
            whisper_cli, whisper_model, ffmpeg, use_gpu=whisper_gpu
        )
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
    # never leave the machine. The default order targets the sweet spot for the
    # always-on security monitor — smart enough for daily use, light enough to
    # run continuously: qwen2.5vl:7b (best all-round, ~6 GB, wants 16 GB RAM),
    # then qwen2.5vl:3b (~3 GB, great on 8 GB), then minicpm-v (~5.5 GB), then
    # moondream (~1.7 GB, tiny/fast fallback), then llava. Only installed models
    # are considered, so the order just decides among what is already pulled;
    # set JARVIS_VISION_MODEL to pin one explicitly.
    # Fall back to Gemini when no local model is present and turbo mode is on.
    # JARVIS_VISION_PROVIDER lets a low-RAM machine outsource vision to the cloud:
    #   "cloud" -> always use Gemini (skip the local model, save RAM)
    #   "local" -> only ever use a local model (never send frames off-device)
    #   "auto"  -> local-first with Gemini fallback (default)
    provider_pref = os.environ.get("JARVIS_VISION_PROVIDER", "auto").strip().lower()
    preferred = os.environ.get("JARVIS_VISION_MODEL")
    candidates = (
        [preferred]
        if preferred
        else ["qwen2.5vl:7b", "qwen2.5vl:3b", "minicpm-v", "moondream", "llava"]
    )
    local_model = (
        None
        if provider_pref == "cloud"
        else next(
            (m for m in candidates if m and OllamaVisionAdapter.available(ollama_base_url, m)),
            None,
        )
    )
    if vision_command:
        adapter = CommandVisionAdapter(vision_command)
    elif local_model:
        # Evict the VLM immediately after each analysis by default: on an 8 GB
        # machine the chat model owns the RAM and vision runs occasionally.
        adapter = OllamaVisionAdapter(
            model=local_model,
            base_url=ollama_base_url,
            keep_alive=os.environ.get("JARVIS_VISION_KEEP_ALIVE", "0").strip() or "0",
        )
    elif provider_pref != "local" and settings.get("turbo_mode") and gemini_key:
        adapter = GeminiVisionAdapter(
            api_key=gemini_key,
            model=os.environ.get("JARVIS_VISION_GEMINI_MODEL", "gemini-2.5-flash"),
        )
    else:
        adapter = UnconfiguredVisionAdapter()
    return VisionManager(adapter=adapter, event_bus=get_event_bus())


def _load_camera_sources() -> list[CameraSource]:
    """Build camera sources from the JSON config at JARVIS_CAMERA_CONFIG.

    The file is a list of ``{"name": ..., "url": "rtsp://..."}`` objects (one per
    NVR channel). Missing/empty file → no sources (monitor idles). When ffmpeg is
    absent every camera becomes an UnconfiguredCameraSource so status still lists
    it with a clear reason instead of the backend failing to start.
    """
    config_path = Path(os.environ.get("JARVIS_CAMERA_CONFIG", "data/cameras.json"))
    if not config_path.is_file():
        return []
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = raw if isinstance(raw, list) else raw.get("cameras", [])
    ffmpeg = shutil.which(os.environ.get("JARVIS_FFMPEG", "ffmpeg")) or os.environ.get(
        "JARVIS_FFMPEG"
    )
    try:
        grab_timeout = float(os.environ.get("JARVIS_SECURITY_GRAB_TIMEOUT_SECONDS", "20"))
    except ValueError:
        grab_timeout = 20.0
    sources: list[CameraSource] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or f"camera-{index + 1}").strip()
        url = str(entry.get("url") or "").strip()
        if not url:
            sources.append(UnconfiguredCameraSource(name, "no RTSP url in config"))
            continue
        if not ffmpeg:
            sources.append(UnconfiguredCameraSource(name, "ffmpeg not installed"))
            continue
        sources.append(
            RTSPCameraSource(
                name=name,
                url=url,
                ffmpeg=ffmpeg,
                timeout_seconds=grab_timeout,
                transport=str(entry.get("transport") or "tcp"),
            )
        )
    return sources


@lru_cache(maxsize=1)
def get_notifier() -> Notifier:
    """Phone push channel: ntfy when a topic is set, else a no-op.

    Live alerts always ride the event bus regardless; this only governs the
    "push to phone with the app closed" channel.
    """
    topic = os.environ.get("JARVIS_NTFY_TOPIC", "").strip()
    if not topic:
        return UnconfiguredNotifier()
    return NtfyNotifier(
        topic=topic,
        base_url=os.environ.get("JARVIS_NTFY_URL", "https://ntfy.sh"),
        token=os.environ.get("JARVIS_NTFY_TOKEN"),
    )


@lru_cache(maxsize=1)
def get_camera_monitor() -> CameraMonitor:
    try:
        interval = float(os.environ.get("JARVIS_SECURITY_INTERVAL_SECONDS", "30"))
    except ValueError:
        interval = 30.0
    try:
        cooldown = float(os.environ.get("JARVIS_SECURITY_COOLDOWN_SECONDS", "180"))
    except ValueError:
        cooldown = 180.0
    watch_raw = os.environ.get("JARVIS_SECURITY_WATCH", "").strip()
    watch_for = [item.strip() for item in watch_raw.split(";") if item.strip()] or None
    return CameraMonitor(
        _load_camera_sources(),
        get_vision_manager(),
        event_bus=get_event_bus(),
        notifier=get_notifier(),
        capture_dir=Path(os.environ.get("JARVIS_SECURITY_CAPTURE_DIR", "data/security")),
        interval_seconds=max(interval, 1.0),
        cooldown_seconds=max(cooldown, 0.0),
        watch_for=watch_for,
        enabled=os.environ.get("JARVIS_SECURITY_MONITOR", "disabled").lower()
        in {"1", "true", "yes", "on", "enabled"},
        max_captures=_env_int("JARVIS_SECURITY_MAX_CAPTURES", 100),
    )


@lru_cache(maxsize=1)
def get_image_manager() -> ImageManager:
    # Adapter priority mirrors vision: a local command wins, then cloud Gemini
    # (turbo), else unconfigured. When a local generator is added later, set
    # JARVIS_IMAGE_COMMAND and it automatically takes priority — no code change.
    image_command = os.environ.get("JARVIS_IMAGE_COMMAND")
    settings = get_settings_store().read()
    gemini_key = str(settings.get("gemini_api_key") or "").strip()
    if image_command:
        adapter = CommandImageAdapter(image_command)
    elif settings.get("turbo_mode") and gemini_key:
        adapter = GeminiImageAdapter(
            api_key=gemini_key,
            model=os.environ.get(
                "JARVIS_IMAGE_GEMINI_MODEL", "gemini-2.0-flash-preview-image-generation"
            ),
        )
    else:
        adapter = UnconfiguredImageAdapter()
    return ImageManager(
        adapter=adapter,
        output_dir=Path(os.environ.get("JARVIS_IMAGE_OUTPUT_DIR", "data/images")),
        event_bus=get_event_bus(),
    )


@lru_cache(maxsize=1)
def get_identity_manager() -> IdentityManager:
    return IdentityManager(get_core().memory, event_bus=get_event_bus())


@lru_cache(maxsize=1)
def get_improvement_manager() -> ImprovementManager:
    core = get_core()
    return ImprovementManager(
        core.memory,
        get_settings_store(),
        core.lm_provider,
        safety_switch=get_safety_switch(),
        event_bus=get_event_bus(),
    )


@lru_cache(maxsize=1)
def get_heartbeat_engine() -> HeartbeatEngine:
    core = get_core()
    try:
        interval = float(os.environ.get("JARVIS_HEARTBEAT_INTERVAL_SECONDS", "1800"))
    except ValueError:
        interval = 1800.0
    return HeartbeatEngine(
        core.memory,
        core.lm_provider,
        get_identity_manager(),
        get_memory_consolidator(),
        get_settings_store(),
        safety_switch=get_safety_switch(),
        event_bus=get_event_bus(),
        improvement=get_improvement_manager(),
        interval_seconds=interval,
        enabled=os.environ.get("JARVIS_HEARTBEAT", "enabled").lower()
        not in {"0", "false", "disabled"},
        # Surface a self-improvement proposal every Nth tick (0 disables).
        propose_every=_env_int("JARVIS_HEARTBEAT_PROPOSE_EVERY", 10),
    )


@lru_cache(maxsize=1)
def get_agent_manager() -> DeepResearchAgent:
    core = get_core()
    return DeepResearchAgent(
        lm_provider=core.lm_provider,
        bot_manager=core.bot_manager,
        memory=core.memory,
        audit_logger=get_audit_logger(),
        event_bus=get_event_bus(),
    )


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
        safety_switch=get_safety_switch(),
    )
    bot_manager.register(
        FileBot(
            permission_manager,
            audit_logger,
            self_root=Path(os.environ.get("JARVIS_SELF_ROOT", PACKAGE_ROOT.parent)),
            snapshot_store=FileSnapshotStore(
                Path(os.environ.get("JARVIS_FILE_SNAPSHOT_DIR", "data/file_snapshots"))
            ),
        )
    )
    bot_manager.register(ResearchBot(permission_manager, audit_logger))
    bot_manager.register(CodeBot(permission_manager, audit_logger))
    bot_manager.register(SystemBot(permission_manager, audit_logger))
    bot_manager.register(ImageBot(permission_manager, audit_logger, get_image_manager()))
    bot_manager.register(DesktopBot(permission_manager, audit_logger))

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
        openrouter_base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        nvidia_base_url=os.environ.get(
            "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
        ),
    )
    skill_manager = SkillManager(
        Path(os.environ.get("JARVIS_SKILLS_DIR", "skills"))
    )
    return JarvisCore(
        memory=memory,
        bot_manager=bot_manager,
        lm_provider=lm_provider,
        audit_logger=audit_logger,
        event_bus=event_bus,
        read_settings=get_settings_store().read,
        skill_manager=skill_manager,
    )
