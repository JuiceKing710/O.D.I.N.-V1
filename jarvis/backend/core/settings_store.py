from __future__ import annotations

import json
import os
import tempfile
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
    # Emergency stop (master spec §Safety). When True, every high-impact bot
    # action is refused and the heartbeat loop pauses until explicitly resumed.
    "emergency_stop": False,
}


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The store is read on every chat turn (turbo switch, truthfulness
        # check) and written by background loops; cache the parsed file and
        # invalidate on mtime/size so hot reads skip disk without going stale.
        self._cached: dict[str, Any] | None = None
        self._cached_stamp: tuple[int, int] | None = None

    def read(self) -> dict[str, Any]:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return dict(DEFAULT_SETTINGS)
        stamp = (stat.st_mtime_ns, stat.st_size)
        if self._cached is None or stamp != self._cached_stamp:
            with self.path.open("r", encoding="utf-8") as handle:
                self._cached = json.load(handle)
            self._cached_stamp = stamp
        return {**DEFAULT_SETTINGS, **self._cached}

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        settings = self.read()
        settings.update(patch)
        # Write-then-rename so a crash mid-write can never leave a truncated
        # settings.json (which would take emergency_stop and permissions with it).
        fd, temp_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(settings, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp_name, self.path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        stat = self.path.stat()
        self._cached = dict(settings)
        self._cached_stamp = (stat.st_mtime_ns, stat.st_size)
        return settings
