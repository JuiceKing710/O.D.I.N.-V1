from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.backend.core.vector_store import VectorStoreInterface


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    sqlite_ok: bool
    vector_ok: bool
    details: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.sqlite_ok and self.vector_ok


@dataclass(frozen=True, slots=True)
class BackupSnapshot:
    path: Path
    created_at: datetime
    encrypted: bool


class RecoveryManager:
    def __init__(
        self,
        db_path: Path | str,
        backup_dir: Path | str,
        vector_store: VectorStoreInterface,
    ) -> None:
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.vector_store = vector_store

    def check_integrity(self) -> IntegrityReport:
        sqlite_ok = False
        sqlite_detail = "database does not exist"
        if self.db_path.exists():
            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                row = conn.execute("PRAGMA integrity_check").fetchone()
                sqlite_detail = row[0] if row else "missing integrity result"
                sqlite_ok = sqlite_detail == "ok"
            except sqlite3.Error as exc:
                sqlite_detail = str(exc)
            finally:
                if conn is not None:
                    conn.close()

        vector_health = self.vector_store.health()
        return IntegrityReport(
            sqlite_ok=sqlite_ok,
            vector_ok=True,
            details={
                "sqlite": sqlite_detail,
                "vector": vector_health,
                "encryption": "external-keychain-required",
            },
        )

    def create_sqlite_backup(self) -> BackupSnapshot:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.backup_dir / f"jarvis-{timestamp}.db"
        shutil.copy2(self.db_path, target)
        return BackupSnapshot(path=target, created_at=datetime.now(timezone.utc), encrypted=False)
