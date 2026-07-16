from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.backend.core.camera_source import CameraSource
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.notifier import Notifier, UnconfiguredNotifier
from jarvis.backend.core.vision_manager import VisionManager

# Default set of things a home security monitor should flag. Overridable so the
# user can narrow it (e.g. only people) or widen it.
DEFAULT_WATCH_FOR = (
    "a person or an unfamiliar face",
    "notable motion or a new object appearing",
    "a package or delivery at the door",
    "a vehicle arriving or leaving",
)

_ALERT_PREFIX = re.compile(r"^\s*alert\b[:\-\s]*", re.IGNORECASE)
_CLEAR_PREFIX = re.compile(r"^\s*clear\b", re.IGNORECASE)


def build_detection_prompt(watch_for: list[str]) -> str:
    """A prompt that makes the vision model return a parseable verdict.

    Small local VLMs are unreliable at strict JSON, so we ask for a leading
    keyword instead: 'ALERT: <one sentence>' when a watched event is present,
    or exactly 'CLEAR' for a normal/empty scene. The monitor keys off that
    prefix; the sentence becomes the alert summary.
    """
    watched = "\n".join(f"- {item}" for item in watch_for)
    return (
        "You are Odin's home security monitor looking at a single still frame "
        "from a surveillance camera. Watch for any of these:\n"
        f"{watched}\n\n"
        "If one or more of them is clearly present, reply with 'ALERT:' followed "
        "by a single concise sentence describing what you see. If the scene looks "
        "normal, empty, or unchanged, reply with exactly 'CLEAR'. Do not guess or "
        "invent detail you cannot see."
    )


def verdict_from_description(description: str) -> tuple[bool, str]:
    """Parse a vision reply into (is_alert, summary).

    Anything starting with 'ALERT' triggers; a leading 'CLEAR' does not. If the
    model ignores the format, fall back to treating a non-empty reply that isn't
    an explicit 'CLEAR' as no-alert (conservative — avoids alarm spam), except we
    still honour an explicit ALERT anywhere at the start.
    """
    text = (description or "").strip()
    if not text or _CLEAR_PREFIX.match(text):
        return False, ""
    if _ALERT_PREFIX.match(text):
        summary = _ALERT_PREFIX.sub("", text, count=1).strip()
        return True, summary or "Something was detected on camera."
    return False, ""


@dataclass(slots=True)
class SecurityAlert:
    alert_id: str
    camera: str
    at: datetime
    summary: str
    capture_name: str | None = None

    def to_api(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "camera": self.camera,
            "at": self.at,
            "summary": self.summary,
            "image_url": (
                f"/api/v1/security/capture/{self.capture_name}" if self.capture_name else None
            ),
        }


@dataclass(slots=True)
class _CameraState:
    source: CameraSource
    last_alert_at: float = 0.0
    last_error: str | None = None
    last_scanned_at: float = field(default=0.0)


class CameraMonitor:
    """Always-on loop that turns Odin's vision into a security detector.

    Each cycle it pulls one frame per camera, asks the vision model whether any
    watched event is present, and on a hit saves the frame, publishes a
    ``security.alert`` event (live in the app) and fires a push notification
    (phone, app closed). A per-camera cooldown keeps a lingering person from
    re-alerting every cycle. The loop mirrors HeartbeatEngine: it survives any
    per-camera error and is skipped cleanly when disabled.
    """

    def __init__(
        self,
        sources: list[CameraSource],
        vision: VisionManager,
        event_bus: EventBus | None = None,
        notifier: Notifier | None = None,
        *,
        capture_dir: Path | str = "data/security",
        interval_seconds: float = 30.0,
        cooldown_seconds: float = 180.0,
        watch_for: list[str] | None = None,
        enabled: bool = False,
        max_captures: int = 100,
        max_alerts: int = 100,
    ) -> None:
        self.vision = vision
        self.event_bus = event_bus
        self.notifier = notifier or UnconfiguredNotifier()
        self.capture_dir = Path(capture_dir)
        self.interval_seconds = max(interval_seconds, 1.0)
        self.cooldown_seconds = max(cooldown_seconds, 0.0)
        self.watch_for = list(watch_for) if watch_for else list(DEFAULT_WATCH_FOR)
        self.enabled = enabled
        self.max_captures = max(max_captures, 1)
        self._cameras = [_CameraState(source=source) for source in sources]
        self._prompt = build_detection_prompt(self.watch_for)
        self._alerts: deque[SecurityAlert] = deque(maxlen=max(max_alerts, 1))
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # --- detection ---------------------------------------------------------

    async def scan_camera(self, state: _CameraState) -> SecurityAlert | None:
        """Grab one frame, judge it, and raise an alert if warranted."""
        state.last_scanned_at = time.time()
        # Both the ffmpeg grab and the vision HTTP call block; keep them off the
        # event loop so one slow camera never stalls the whole backend.
        frame = await asyncio.to_thread(state.source.grab_frame)
        description = await asyncio.to_thread(
            self.vision.analyze_image, frame, ".jpg", self._prompt
        )
        state.last_error = None
        is_alert, summary = verdict_from_description(description)
        if not is_alert:
            return None
        now = time.time()
        if now - state.last_alert_at < self.cooldown_seconds:
            # Still within the quiet window for this camera; note it but stay silent.
            return None
        state.last_alert_at = now
        capture_name = self._save_capture(state.source.name, frame)
        alert = SecurityAlert(
            alert_id=uuid.uuid4().hex[:12],
            camera=state.source.name,
            at=datetime.now(timezone.utc),
            summary=summary,
            capture_name=capture_name,
        )
        self._alerts.appendleft(alert)
        self._dispatch(alert)
        return alert

    async def scan_all(self) -> list[SecurityAlert]:
        alerts: list[SecurityAlert] = []
        for state in self._cameras:
            try:
                alert = await self.scan_camera(state)
                if alert is not None:
                    alerts.append(alert)
            except Exception as exc:  # noqa: BLE001 - one bad camera must not stop the sweep
                state.last_error = str(exc)
                self.last_error = str(exc)
        return alerts

    def _dispatch(self, alert: SecurityAlert) -> None:
        if self.event_bus is not None:
            self.event_bus.publish("security.alert", alert.to_api())
        # Push is best-effort: a failed notification must never crash the loop or
        # suppress the live/event-bus alert that already fired.
        try:
            self.notifier.notify(
                title=f"Odin: {alert.camera}",
                message=alert.summary,
                priority="high",
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"push failed: {exc}"

    def _save_capture(self, camera: str, frame: bytes) -> str | None:
        try:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", camera).strip("-") or "camera"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            name = f"{slug}-{stamp}-{uuid.uuid4().hex[:6]}.jpg"
            (self.capture_dir / name).write_bytes(frame)
            self._prune_captures()
            return name
        except OSError as exc:
            self.last_error = f"could not save capture: {exc}"
            return None

    def _prune_captures(self) -> None:
        files = sorted(
            (p for p in self.capture_dir.glob("*.jpg") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        for stale in files[: max(len(files) - self.max_captures, 0)]:
            stale.unlink(missing_ok=True)

    # --- status ------------------------------------------------------------

    def recent_alerts(self, limit: int = 25) -> list[SecurityAlert]:
        return list(self._alerts)[: max(limit, 0)]

    def status(self) -> dict[str, Any]:
        last = self._alerts[0] if self._alerts else None
        return {
            "enabled": self.enabled,
            "running": self._task is not None and not self._task.done(),
            "interval_seconds": self.interval_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "watch_for": self.watch_for,
            "notifier": self.notifier.name,
            "push_enabled": self.notifier.configured,
            "cameras": [
                {
                    "name": state.source.name,
                    "configured": state.source.configured,
                    "last_error": state.last_error,
                    "last_scanned_at": (
                        datetime.fromtimestamp(state.last_scanned_at, tz=timezone.utc).isoformat()
                        if state.last_scanned_at
                        else None
                    ),
                }
                for state in self._cameras
            ],
            "alert_count": len(self._alerts),
            "last_alert_at": last.at.isoformat() if last else None,
            "last_error": self.last_error,
        }

    # --- background loop ---------------------------------------------------

    def start(self) -> None:
        if not self.enabled or self._task is not None or not self._cameras:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="jarvis-camera-monitor")

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
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
                return
            except TimeoutError:
                pass
            try:
                await self.scan_all()
            except Exception as exc:  # noqa: BLE001 - the loop must survive any sweep error
                self.last_error = str(exc)
