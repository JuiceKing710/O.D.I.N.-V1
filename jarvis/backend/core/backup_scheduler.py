from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.recovery_manager import RecoveryManager


@dataclass(frozen=True, slots=True)
class BackupScheduleStatus:
    enabled: bool
    hour: int
    retention: int
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_backup: str | None
    last_error: str | None

    def to_api(self) -> dict:
        return {
            "enabled": self.enabled,
            "hour": self.hour,
            "retention": self.retention,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_backup": self.last_backup,
            "last_error": self.last_error,
        }


class BackupScheduler:
    def __init__(
        self,
        recovery_manager: RecoveryManager,
        event_bus: EventBus | None = None,
        *,
        enabled: bool = True,
        hour: int = 4,
        retention: int = 30,
    ) -> None:
        if hour not in range(24):
            raise ValueError("Backup schedule hour must be between 0 and 23")
        if retention < 1:
            raise ValueError("Backup retention must keep at least one backup")
        self.recovery_manager = recovery_manager
        self.event_bus = event_bus
        self.enabled = enabled
        self.hour = hour
        self.retention = retention
        self.next_run_at: datetime | None = None
        self.last_run_at: datetime | None = None
        self.last_backup: str | None = None
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def status(self) -> BackupScheduleStatus:
        return BackupScheduleStatus(
            enabled=self.enabled,
            hour=self.hour,
            retention=self.retention,
            next_run_at=self.next_run_at,
            last_run_at=self.last_run_at,
            last_backup=self.last_backup,
            last_error=self.last_error,
        )

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="jarvis-daily-backup")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_backup(self) -> None:
        self.last_run_at = datetime.now().astimezone()
        try:
            snapshot = await asyncio.to_thread(self.recovery_manager.create_sqlite_backup)
            await asyncio.to_thread(self.recovery_manager.prune_backups, self.retention)
            self.last_backup = str(snapshot.path)
            self.last_error = None
            self._publish("backup.completed", {"backup": self.last_backup})
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            self.last_error = str(exc)
            self._publish("backup.failed", {"error": self.last_error})

    async def _run(self) -> None:
        if self.needs_catch_up():
            await self.run_backup()
        while not self._stop.is_set():
            now = datetime.now().astimezone()
            self.next_run_at = self.next_run(now)
            timeout = max((self.next_run_at - now).total_seconds(), 0)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=timeout)
            except TimeoutError:
                await self.run_backup()

    def needs_catch_up(self, now: datetime | None = None) -> bool:
        current = now or datetime.now().astimezone()
        if current.hour < self.hour:
            return False
        backups = self.recovery_manager.list_backups()
        if not backups:
            return True
        latest_local_date = backups[0].created_at.astimezone(current.tzinfo).date()
        return latest_local_date < current.date()

    def next_run(self, now: datetime | None = None) -> datetime:
        current = now or datetime.now().astimezone()
        scheduled = current.replace(hour=self.hour, minute=0, second=0, microsecond=0)
        if scheduled <= current:
            scheduled += timedelta(days=1)
        return scheduled

    def _publish(self, event_type: str, payload: dict) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(event_type, payload)
