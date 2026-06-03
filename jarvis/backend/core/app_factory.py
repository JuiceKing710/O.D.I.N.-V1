from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from jarvis.backend.bots.code_bot import CodeBot
from jarvis.backend.bots.file_bot import FileBot
from jarvis.backend.bots.research_bot import ResearchBot
from jarvis.backend.bots.system_bot import SystemBot
from jarvis.backend.core.bot_manager import BotManager
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.lm_provider import EchoLMProvider, LMStudioProvider
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import PermissionManager


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _default_db_path() -> Path:
    return Path(os.environ.get("JARVIS_DB_PATH", "data/jarvis.db"))


@lru_cache(maxsize=1)
def get_permission_manager() -> PermissionManager:
    return PermissionManager.from_manifest(PACKAGE_ROOT / "config" / "permissions.json")


@lru_cache(maxsize=1)
def get_settings_store() -> SettingsStore:
    return SettingsStore(Path(os.environ.get("JARVIS_SETTINGS_PATH", "data/settings.json")))


@lru_cache(maxsize=1)
def get_core() -> JarvisCore:
    permission_manager = get_permission_manager()
    audit_logger = AuditLogger(Path(os.environ.get("JARVIS_AUDIT_LOG", "data/audit.log")))
    memory = MemoryManager(_default_db_path())
    bot_manager = BotManager(permission_manager=permission_manager, audit_logger=audit_logger)
    bot_manager.register(FileBot(permission_manager, audit_logger))
    bot_manager.register(ResearchBot(permission_manager, audit_logger))
    bot_manager.register(CodeBot(permission_manager, audit_logger))
    bot_manager.register(SystemBot(permission_manager, audit_logger))

    lm_base_url = os.environ.get("LM_STUDIO_BASE_URL")
    lm_provider = LMStudioProvider(lm_base_url) if lm_base_url else EchoLMProvider()
    return JarvisCore(
        memory=memory,
        bot_manager=bot_manager,
        lm_provider=lm_provider,
        audit_logger=audit_logger,
    )
