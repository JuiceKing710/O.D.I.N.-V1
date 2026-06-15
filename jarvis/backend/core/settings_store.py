from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "voice_mode": "push_to_talk",
    "model_name": "local-default",
    "theme": "system",
    "permissions": {},
    "turbo_mode": False,
    # When enabled, Odin verifies each reply against the question and provided
    # context before sending it (generate -> critique -> one corrective regen).
    # Off by default: it costs extra model calls and disables live streaming.
    "truthfulness_check": False,
}


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULT_SETTINGS)
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {**DEFAULT_SETTINGS, **data}

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        settings = self.read()
        settings.update(patch)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return settings

