from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit


def redact_url(url: str) -> str:
    """Strip any ``user:pass@`` credentials from a URL for safe logging/events.

    Camera RTSP URLs almost always embed the NVR password; it must never reach
    an error string, event payload, or the audit log.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<camera-url>"
    if not parts.hostname:
        return url
    host = parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"***@{host}" if (parts.username or parts.password) else host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


class CameraSource(Protocol):
    name: str
    configured: bool

    def grab_frame(self) -> bytes:
        """Return a single still frame as JPEG bytes, or raise RuntimeError."""
        raise NotImplementedError


class UnconfiguredCameraSource:
    """No-op source used when a camera can't be built (e.g. ffmpeg missing).

    Mirrors the Unconfigured* adapter pattern used across Odin: the monitor can
    hold one without special-casing, and it simply never produces a frame.
    """

    configured = False

    def __init__(self, name: str = "unconfigured", reason: str = "not configured") -> None:
        self.name = name
        self.reason = reason

    def grab_frame(self) -> bytes:
        raise RuntimeError(f"Camera '{self.name}' is not configured: {self.reason}")


class RTSPCameraSource:
    """Grabs a single JPEG frame from an RTSP feed via a one-shot ffmpeg call.

    This is the common denominator for NVR/IP camera systems (ZOSI, Reolink,
    Amcrest, Hikvision, ONVIF): the NVR exposes one RTSP URL per channel and
    ffmpeg pulls a single keyframe without holding the stream open. Credentials
    live in the URL and are redacted from every error message.
    """

    configured = True

    def __init__(
        self,
        name: str,
        url: str,
        ffmpeg: str = "ffmpeg",
        timeout_seconds: float = 20.0,
        transport: str = "tcp",
    ) -> None:
        if not url.strip():
            raise ValueError("An RTSP URL is required")
        self.name = name
        self.url = url.strip()
        self.ffmpeg = ffmpeg
        # RTSP frame pulls are slow to connect; the caller runs this off the
        # event loop and the loop's per-cycle budget must cover the slowest cam.
        self.timeout_seconds = timeout_seconds
        # TCP transport is far more reliable than the UDP default over Wi-Fi /
        # busy LANs (no torn frames), at a small latency cost.
        self.transport = transport

    def grab_frame(self) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "frame.jpg"
            command = [
                self.ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-rtsp_transport",
                self.transport,
                "-i",
                self.url,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-f",
                "image2",
                "-y",
                str(target),
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Timed out grabbing a frame from {redact_url(self.url)} "
                    f"after {self.timeout_seconds:.0f}s"
                ) from exc
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "ffmpeg was not found — install it (macOS: `brew install ffmpeg`) "
                    "to read camera streams"
                ) from exc
            if result.returncode != 0 or not target.is_file():
                detail = (result.stderr or "").strip().replace(self.url, redact_url(self.url))
                raise RuntimeError(
                    f"Could not read camera '{self.name}' ({redact_url(self.url)}): "
                    f"{detail or 'ffmpeg produced no frame'}"
                )
            data = target.read_bytes()
        if not data:
            raise RuntimeError(f"Camera '{self.name}' returned an empty frame")
        return data
