from __future__ import annotations

import os
import json
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from jarvis.backend.core.vector_store import VectorStoreInterface

BACKUP_MAGIC = b"JARVISBK1"
SALT_SIZE = 16
NONCE_SIZE = 12
PBKDF2_ITERATIONS = 600_000


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


@dataclass(frozen=True, slots=True)
class RestoreSnapshot:
    path: Path
    restored_from: Path
    safety_backup: Path | None
    created_at: datetime
    encrypted: bool


class RecoveryManager:
    def __init__(
        self,
        db_path: Path | str,
        backup_dir: Path | str,
        vector_store: VectorStoreInterface,
        encryption_key: str | bytes | None = None,
        db_lock: threading.RLock | None = None,
        settings_path: Path | str | None = None,
        audit_log_path: Path | str | None = None,
        vector_path: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.vector_store = vector_store
        self.db_lock = db_lock or threading.RLock()
        self.settings_path = Path(settings_path) if settings_path else None
        self.audit_log_path = Path(audit_log_path) if audit_log_path else None
        self.vector_path = Path(vector_path) if vector_path else None
        self.encryption_key = (
            encryption_key.encode("utf-8") if isinstance(encryption_key, str) else encryption_key
        )

    def check_integrity(self) -> IntegrityReport:
        with self.db_lock:
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
                "encryption": "configured" if self.encryption_key else "not configured",
            },
        )

    def create_sqlite_backup(self) -> BackupSnapshot:
        with self.db_lock:
            if not self.db_path.exists():
                raise FileNotFoundError(f"Database not found: {self.db_path}")
            self._require_encryption_key()
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            created_at = datetime.now(timezone.utc)
            timestamp = created_at.strftime("%Y%m%dT%H%M%S%fZ")
            target = self.backup_dir / f"jarvis-{timestamp}.db.enc"
            with tempfile.TemporaryDirectory(dir=self.backup_dir) as temporary_dir:
                staging = Path(temporary_dir)
                database_snapshot = staging / "jarvis.db"
                with closing(sqlite3.connect(self.db_path)) as source:
                    with closing(sqlite3.connect(database_snapshot)) as backup:
                        source.backup(backup)
                archive_path = staging / "jarvis-backup.zip"
                self._create_bundle_archive(archive_path, database_snapshot, created_at)
                target.write_bytes(self._encrypt(archive_path.read_bytes()))
            return BackupSnapshot(path=target, created_at=created_at, encrypted=True)

    def list_backups(self) -> list[BackupSnapshot]:
        if not self.backup_dir.exists():
            return []
        snapshots = [
            BackupSnapshot(
                path=path,
                created_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                encrypted=True,
            )
            for path in self.backup_dir.glob("jarvis-*.db.enc")
            if path.is_file()
        ]
        return sorted(snapshots, key=lambda snapshot: snapshot.created_at, reverse=True)

    def prune_backups(self, keep: int = 30) -> int:
        if keep < 1:
            raise ValueError("Backup retention must keep at least one backup")
        stale = self.list_backups()[keep:]
        for snapshot in stale:
            snapshot.path.unlink(missing_ok=True)
        return len(stale)

    def restore_sqlite_backup(self, filename: str) -> RestoreSnapshot:
        with self.db_lock:
            self._require_encryption_key()
            source = self._resolve_backup(filename)
            plaintext = self._decrypt(source.read_bytes())
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.db_path.parent) as temporary_dir:
                staging = Path(temporary_dir)
                temporary_path = staging / "jarvis.db"
                bundle = plaintext.startswith(b"PK")
                if bundle:
                    archive_path = staging / "backup.zip"
                    archive_path.write_bytes(plaintext)
                    with zipfile.ZipFile(archive_path) as archive:
                        archive.extractall(staging / "bundle")
                    temporary_path = staging / "bundle" / "database" / "jarvis.db"
                else:
                    temporary_path.write_bytes(plaintext)
                self._validate_sqlite(temporary_path)
                safety_backup = self.create_sqlite_backup() if self.db_path.exists() else None
                os.replace(temporary_path, self.db_path)
                if bundle:
                    self._restore_optional_bundle_files(staging / "bundle")
            return RestoreSnapshot(
                path=self.db_path,
                restored_from=source,
                safety_backup=safety_backup.path if safety_backup else None,
                created_at=datetime.now(timezone.utc),
                encrypted=True,
            )

    def _create_bundle_archive(
        self,
        archive_path: Path,
        database_snapshot: Path,
        created_at: datetime,
    ) -> None:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(database_snapshot, "database/jarvis.db")
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": 2,
                        "created_at": created_at.isoformat(),
                        "includes": ["database", "settings", "audit", "vector"],
                    },
                    sort_keys=True,
                ),
            )
            for source, name in (
                (self.settings_path, "settings/settings.json"),
                (self.audit_log_path, "audit/audit.log"),
            ):
                if source and source.is_file():
                    archive.write(source, name)
            if self.vector_path and self.vector_path.is_dir():
                for path in self.vector_path.rglob("*"):
                    if path.is_file():
                        archive.write(path, Path("vector") / path.relative_to(self.vector_path))

    def _restore_optional_bundle_files(self, bundle_path: Path) -> None:
        for source, target in (
            (bundle_path / "settings" / "settings.json", self.settings_path),
            (bundle_path / "audit" / "audit.log", self.audit_log_path),
        ):
            if target and source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
        source_vector = bundle_path / "vector"
        if self.vector_path and source_vector.is_dir():
            temporary_vector = self.vector_path.with_name(f"{self.vector_path.name}.restore")
            shutil.rmtree(temporary_vector, ignore_errors=True)
            shutil.copytree(source_vector, temporary_vector)
            shutil.rmtree(self.vector_path, ignore_errors=True)
            os.replace(temporary_vector, self.vector_path)

    def _resolve_backup(self, filename: str) -> Path:
        backup_dir = self.backup_dir.resolve()
        source = (backup_dir / filename).resolve()
        if source.parent != backup_dir or not source.is_file() or source.suffix != ".enc":
            raise FileNotFoundError(f"Encrypted backup not found: {filename}")
        return source

    def _require_encryption_key(self) -> bytes:
        if not self.encryption_key:
            raise RuntimeError("Encrypted backups require JARVIS_BACKUP_KEY")
        return self.encryption_key

    def _derive_key(self, salt: bytes) -> bytes:
        return PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        ).derive(self._require_encryption_key())

    def _encrypt(self, plaintext: bytes) -> bytes:
        salt = os.urandom(SALT_SIZE)
        nonce = os.urandom(NONCE_SIZE)
        ciphertext = AESGCM(self._derive_key(salt)).encrypt(nonce, plaintext, BACKUP_MAGIC)
        return BACKUP_MAGIC + salt + nonce + ciphertext

    def _decrypt(self, encrypted: bytes) -> bytes:
        header_size = len(BACKUP_MAGIC) + SALT_SIZE + NONCE_SIZE
        if len(encrypted) <= header_size or not encrypted.startswith(BACKUP_MAGIC):
            raise ValueError("Invalid encrypted backup format")
        salt_start = len(BACKUP_MAGIC)
        nonce_start = salt_start + SALT_SIZE
        ciphertext_start = nonce_start + NONCE_SIZE
        salt = encrypted[salt_start:nonce_start]
        nonce = encrypted[nonce_start:ciphertext_start]
        try:
            return AESGCM(self._derive_key(salt)).decrypt(
                nonce,
                encrypted[ciphertext_start:],
                BACKUP_MAGIC,
            )
        except InvalidTag as exc:
            raise ValueError("Encrypted backup authentication failed") from exc

    @staticmethod
    def _validate_sqlite(path: Path) -> None:
        try:
            with closing(sqlite3.connect(path)) as connection:
                row = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as exc:
            raise ValueError(f"Backup is not a valid SQLite database: {exc}") from exc
        if not row or row[0] != "ok":
            raise ValueError(f"Backup SQLite integrity check failed: {row[0] if row else 'unknown'}")
