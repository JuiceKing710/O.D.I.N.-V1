from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import psutil

from jarvis.backend.core.event_bus import EventBus


class SystemMonitor:
    """Samples host telemetry and streams it over the event bus."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        *,
        interval_seconds: float = 2.0,
        disk_path: str = "/",
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("Metrics interval must be positive")
        self.event_bus = event_bus
        self.interval_seconds = interval_seconds
        self.disk_path = disk_path
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_net: tuple[float, Any] | None = None
        psutil.cpu_percent(interval=None)

    def snapshot(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(self.disk_path)
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count": psutil.cpu_count() or 0,
            "memory": {
                "percent": memory.percent,
                "used_bytes": memory.used,
                "total_bytes": memory.total,
            },
            "disk": {
                "percent": disk.percent,
                "used_bytes": disk.used,
                "total_bytes": disk.total,
            },
            "network": self._network_rates(),
            "battery": self._battery(),
            "uptime_seconds": max(0.0, time.time() - psutil.boot_time()),
            "sampled_at": datetime.now(timezone.utc).isoformat(),
        }

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="jarvis-system-monitor")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            if self.event_bus is not None:
                try:
                    self.event_bus.publish(
                        "system.metrics", self.snapshot(), transient=True
                    )
                    self.last_error = None
                except Exception as exc:  # pragma: no cover - host API hiccups
                    self.last_error = str(exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue

    def _network_rates(self) -> dict[str, float | int]:
        counters = psutil.net_io_counters()
        now = time.monotonic()
        sent_per_sec = 0.0
        recv_per_sec = 0.0
        if self._last_net is not None:
            last_time, last_counters = self._last_net
            elapsed = now - last_time
            if elapsed > 0:
                sent_per_sec = max(0, counters.bytes_sent - last_counters.bytes_sent) / elapsed
                recv_per_sec = max(0, counters.bytes_recv - last_counters.bytes_recv) / elapsed
        self._last_net = (now, counters)
        return {
            "sent_bytes_per_sec": sent_per_sec,
            "recv_bytes_per_sec": recv_per_sec,
            "total_sent_bytes": counters.bytes_sent,
            "total_recv_bytes": counters.bytes_recv,
        }

    @staticmethod
    def _battery() -> dict[str, Any] | None:
        try:
            battery = psutil.sensors_battery()
        except (AttributeError, NotImplementedError):  # pragma: no cover - host specific
            return None
        if battery is None:
            return None
        return {
            "percent": battery.percent,
            "plugged": battery.power_plugged,
        }
