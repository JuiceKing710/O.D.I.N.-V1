from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from jarvis.backend.utils.atomic_write import atomic_write_bytes


class FileSnapshotStore:
    """Pre-write snapshots so a FileBot edit can be undone.

    Before FileBot overwrites a path, it asks the store to snapshot the prior
    state: the file's bytes, or a marker that the file did not exist. ``restore``
    pops the most recent snapshot for a path and returns the file to that state
    (rewriting the old bytes, or deleting a file that the edit had created). A
    rolling cap keeps the directory bounded, mirroring the image cache.

    Snapshots are stored as plain blobs plus a JSON index, so they survive a
    restart and are covered by the same data/ backups as everything else.
    """

    def __init__(
        self,
        root: Path | str,
        max_snapshots: int = 50,
        max_blob_bytes: int = 5_000_000,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_snapshots = max(1, int(max_snapshots))
        self.max_blob_bytes = max(0, int(max_blob_bytes))
        self._index_path = self.root / "index.json"
        self._lock = threading.RLock()

    def snapshot(self, path: Path | str) -> str | None:
        """Record the current state of ``path`` before it is overwritten.

        Returns a snapshot id, or ``None`` when the file is too large to snapshot
        (in which case the impending write is not undoable). A path that does not
        yet exist is snapshotted as "absent" so undo can remove the created file.
        """
        path = Path(path).expanduser().resolve()
        existed = path.is_file()
        if existed and path.stat().st_size > self.max_blob_bytes:
            return None
        snapshot_id = uuid4().hex
        entry: dict[str, Any] = {
            "snapshot_id": snapshot_id,
            "path": str(path),
            "existed": existed,
            "blob": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            if existed:
                blob_name = f"{snapshot_id}.bin"
                self._atomic_write_bytes(self.root / blob_name, path.read_bytes())
                entry["blob"] = blob_name
            index = self._load_index()
            index.append(entry)
            self._prune(index)
            self._save_index(index)
        return snapshot_id

    def restore(self, path: Path | str) -> bool:
        """Undo the most recent snapshotted change to ``path``.

        Returns ``True`` if a snapshot was applied, ``False`` if none exists.
        """
        path = Path(path).expanduser().resolve()
        target = str(path)
        with self._lock:
            index = self._load_index()
            for position in range(len(index) - 1, -1, -1):
                if index[position]["path"] == target:
                    entry = index.pop(position)
                    self._apply(entry, path)
                    self._save_index(index)
                    return True
        return False

    def history(self, path: Path | str) -> list[dict[str, Any]]:
        """Return the snapshots recorded for ``path``, newest last."""
        target = str(Path(path).expanduser().resolve())
        with self._lock:
            return [entry for entry in self._load_index() if entry["path"] == target]

    # ---- internals --------------------------------------------------------

    def _apply(self, entry: dict[str, Any], path: Path) -> None:
        if entry.get("existed") and entry.get("blob"):
            blob = self.root / entry["blob"]
            data = blob.read_bytes() if blob.is_file() else b""
            self._atomic_write_bytes(path, data)
            blob.unlink(missing_ok=True)
        else:
            # The file did not exist before the edit, so undoing removes it.
            path.unlink(missing_ok=True)

    def _load_index(self) -> list[dict[str, Any]]:
        if not self._index_path.is_file():
            return []
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save_index(self, index: list[dict[str, Any]]) -> None:
        self._atomic_write_bytes(
            self._index_path, json.dumps(index, indent=2).encode("utf-8")
        )

    def _prune(self, index: list[dict[str, Any]]) -> None:
        while len(index) > self.max_snapshots:
            oldest = index.pop(0)
            blob = oldest.get("blob")
            if blob:
                (self.root / blob).unlink(missing_ok=True)

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        atomic_write_bytes(path, data)
