"""Continuous security-camera monitoring for Odin.

Reads the camera list written by ``scripts/setup_cameras.py`` (``data/cameras.json``)
and watches each RTSP stream. The load profile is deliberately shaped for modest
hardware (an 8 GB MacBook running a local VLM): every tick we pull a tiny
grayscale thumbnail per camera and diff it against the previous one — cheap, pure
Python, no numpy — and only when a camera actually *changes* do we grab a full
frame and spend a vision-model call describing it. So an idle house costs almost
nothing; the expensive path fires on motion, then respects a per-camera cooldown
so a lingering visitor doesn't re-trigger every tick.

Everything degrades to a no-op instead of raising (matching the rest of the
codebase): no ``cameras.json`` → nothing to watch, ffmpeg missing → the grab
returns ``None`` and the loop records it in ``last_error`` and keeps running.

Notable events are published on the :class:`EventBus` (``security.motion`` and
``security.alert``) so the UI and any connected phone receive them live, and —
when a memory manager is supplied — persisted as ``security`` documents so Odin
can answer "what happened while I was out?" after the fact.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.vision_manager import VisionManager


DEFAULT_SECURITY_PROMPT = (
    "You are Odin's security monitor watching a home camera feed. In one or two "
    "concise sentences, describe what changed in the scene: any people, vehicles, "
    "animals, or packages, what they appear to be doing, and anything that looks "
    "unusual or worth the owner's attention. If nothing of note is present, say so "
    "briefly."
)

# The motion thumbnail is a fixed-size grayscale frame; a small edge keeps the
# per-tick decode and diff trivially cheap while still catching real movement.
_SIGNATURE_EDGE = 64
_SIGNATURE_SIZE = _SIGNATURE_EDGE * _SIGNATURE_EDGE


@dataclass(frozen=True, slots=True)
class CameraConfig:
    name: str
    url: str


def load_cameras(path: Path | str) -> list[CameraConfig]:
    """Parse ``data/cameras.json`` into camera configs, tolerant of a missing or
    malformed file (returns ``[]`` so the monitor simply has nothing to watch).

    The file is a list of ``{"name": ..., "url": ...}`` objects — exactly what
    ``scripts/setup_cameras.py`` writes. Entries without a URL are skipped.
    """
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    cameras: list[CameraConfig] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        name = str(item.get("name") or "").strip() or f"Camera {index}"
        cameras.append(CameraConfig(name=name, url=url))
    return cameras


def mean_abs_diff(a: bytes, b: bytes) -> float:
    """Mean absolute per-byte difference of two equal-length frames (0–255).

    A cheap, dependency-free motion score: identical frames give 0, a fully
    changed frame approaches 255. Mismatched lengths return 0.0 — the caller
    treats that as "no comparison possible" and re-baselines.
    """
    if len(a) != len(b) or not a:
        return 0.0
    total = 0
    for x, y in zip(a, b):
        total += x - y if x >= y else y - x
    return total / len(a)


def ffmpeg_signature(
    url: str, ffmpeg: str = "ffmpeg", timeout_seconds: float = 12.0
) -> bytes | None:
    """Grab one frame and return it as a 64×64 grayscale raw thumbnail.

    Returns ``None`` on any failure (unreachable camera, ffmpeg missing, timeout)
    so the monitor can record it and move on rather than crash the loop.
    """
    command = [
        ffmpeg,
        "-nostdin",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-rw_timeout",
        str(int(timeout_seconds * 1_000_000)),  # microseconds
        "-i",
        url,
        "-frames:v",
        "1",
        "-vf",
        f"scale={_SIGNATURE_EDGE}:{_SIGNATURE_EDGE},format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    data = _run_ffmpeg(command, timeout_seconds)
    if data is None or len(data) != _SIGNATURE_SIZE:
        return None
    return data


def ffmpeg_jpeg(
    url: str, ffmpeg: str = "ffmpeg", timeout_seconds: float = 12.0, max_width: int = 640
) -> bytes | None:
    """Grab one full frame as a downscaled JPEG for the vision model.

    Downscaled to ``max_width`` (keeping aspect) to stay light on the VLM, in the
    same spirit as the frontend webcam capture. Returns ``None`` on failure.
    """
    command = [
        ffmpeg,
        "-nostdin",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-rw_timeout",
        str(int(timeout_seconds * 1_000_000)),
        "-i",
        url,
        "-frames:v",
        "1",
        "-vf",
        f"scale='min({max_width},iw)':-2",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    data = _run_ffmpeg(command, timeout_seconds)
    return data or None


def _run_ffmpeg(command: list[str], timeout_seconds: float) -> bytes | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds + 5,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


@dataclass(frozen=True, slots=True)
class SecurityStatus:
    enabled: bool
    running: bool
    configured: bool
    camera_count: int
    interval_seconds: float
    alerts_total: int
    last_alert_at: str | None
    last_error: str | None


class SecurityMonitor:
    """Motion-gated continuous monitor over a set of RTSP cameras.

    Follows the same background-loop shape as the other always-on managers
    (``start`` / ``stop`` around an ``asyncio`` task): each tick polls every
    camera, and any camera whose scene changed beyond ``motion_threshold`` gets a
    vision-model description (subject to ``cooldown_seconds`` per camera). The
    frame grabbers are injectable so the tick is testable without ffmpeg or a
    live camera.
    """

    def __init__(
        self,
        vision: VisionManager,
        event_bus: EventBus | None = None,
        memory: MemoryManager | None = None,
        *,
        cameras_path: Path | str = "data/cameras.json",
        interval_seconds: float = 15.0,
        motion_threshold: float = 8.0,
        cooldown_seconds: float = 60.0,
        enabled: bool = True,
        username: str = "local-user",
        ffmpeg: str = "ffmpeg",
        timeout_seconds: float = 12.0,
        prompt: str = DEFAULT_SECURITY_PROMPT,
        signature_grabber: Callable[[str], bytes | None] | None = None,
        frame_grabber: Callable[[str], bytes | None] | None = None,
    ) -> None:
        self.vision = vision
        self.event_bus = event_bus
        self.memory = memory
        self.cameras_path = Path(cameras_path)
        self.interval_seconds = max(interval_seconds, 1.0)
        self.motion_threshold = max(motion_threshold, 0.0)
        self.cooldown_seconds = max(cooldown_seconds, 0.0)
        self.enabled = enabled
        self.username = username
        self.prompt = prompt
        self.cameras: list[CameraConfig] = load_cameras(self.cameras_path)
        self._signature_grabber = signature_grabber or (
            lambda url: ffmpeg_signature(url, ffmpeg=ffmpeg, timeout_seconds=timeout_seconds)
        )
        self._frame_grabber = frame_grabber or (
            lambda url: ffmpeg_jpeg(url, ffmpeg=ffmpeg, timeout_seconds=timeout_seconds)
        )
        self._last_sig: dict[str, bytes] = {}
        self._last_alert_at: dict[str, float] = {}
        self._alerts_total = 0
        self._last_alert_stamp: str | None = None
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def reload(self) -> None:
        """Re-read the camera config (e.g. after re-running setup_cameras.py)."""
        self.cameras = load_cameras(self.cameras_path)

    def status(self) -> SecurityStatus:
        vision_ok = self.vision.status().configured
        return SecurityStatus(
            enabled=self.enabled,
            running=self._task is not None and not self._task.done(),
            configured=bool(self.cameras) and vision_ok,
            camera_count=len(self.cameras),
            interval_seconds=self.interval_seconds,
            alerts_total=self._alerts_total,
            last_alert_at=self._last_alert_stamp,
            last_error=self.last_error,
        )

    async def tick(self) -> dict[str, Any]:
        """Poll every camera once. Returns a per-tick summary."""
        checked = 0
        motion: list[str] = []
        alerts: list[dict[str, Any]] = []
        errors = 0
        for camera in self.cameras:
            checked += 1
            try:
                result = await asyncio.to_thread(self._check_camera, camera)
            except Exception as exc:  # noqa: BLE001 - one bad camera must not stop the sweep
                errors += 1
                self.last_error = f"{camera.name}: {exc}"
                continue
            if result is None:
                errors += 1
                continue
            if result.get("motion"):
                motion.append(camera.name)
            if result.get("alert"):
                alerts.append(result["alert"])
        summary = {
            "checked": checked,
            "motion": motion,
            "alerts": alerts,
            "errors": errors,
        }
        return summary

    def _check_camera(self, camera: CameraConfig) -> dict[str, Any] | None:
        """Poll a single camera (runs in a worker thread). ``None`` = grab failed."""
        signature = self._signature_grabber(camera.url)
        if signature is None:
            self.last_error = (
                f"{camera.name}: could not grab a frame "
                "(camera unreachable or ffmpeg missing)"
            )
            return None
        self.last_error = None
        previous = self._last_sig.get(camera.name)
        self._last_sig[camera.name] = signature
        if previous is None:
            return {"motion": False, "alert": None}  # first frame = baseline
        score = mean_abs_diff(previous, signature)
        if score < self.motion_threshold:
            return {"motion": False, "alert": None}
        self._publish("security.motion", {"camera": camera.name, "score": round(score, 2)})
        alert = self._maybe_describe(camera, score)
        return {"motion": True, "alert": alert}

    def _maybe_describe(self, camera: CameraConfig, score: float) -> dict[str, Any] | None:
        """Run the VLM on a changed camera, respecting the per-camera cooldown."""
        now = time.monotonic()
        last = self._last_alert_at.get(camera.name)
        if last is not None and (now - last) < self.cooldown_seconds:
            return None
        if not self.vision.status().configured:
            return None
        frame = self._frame_grabber(camera.url)
        if not frame:
            return None
        description = self.vision.analyze_image(frame, prompt=self.prompt).strip()
        if not description:
            return None
        self._last_alert_at[camera.name] = now
        self._alerts_total += 1
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self._last_alert_stamp = stamp
        alert = {
            "camera": camera.name,
            "description": description,
            "score": round(score, 2),
            "at": stamp,
        }
        self._publish("security.alert", alert)
        self._persist(camera, description, stamp)
        return alert

    def _persist(self, camera: CameraConfig, description: str, stamp: str) -> None:
        """Save an alert as a durable ``security`` document, best-effort."""
        if self.memory is None:
            return
        try:
            user = self.memory.get_or_create_user(self.username)
            self.memory.save_document(
                user.user_id,
                document_id=f"security-{uuid.uuid4().hex[:12]}",
                source="security",
                content=f"[{stamp}] {camera.name}: {description}",
            )
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            self.last_error = f"persist failed: {exc}"

    # --- background loop ---------------------------------------------------

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="jarvis-security-monitor")

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
                await self.tick()
            except Exception as exc:  # noqa: BLE001 - the loop must survive any tick error
                self.last_error = str(exc)

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(event_type, payload)
