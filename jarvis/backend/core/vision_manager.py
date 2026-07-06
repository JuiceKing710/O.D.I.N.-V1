from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import urllib.error
import urllib.request
from base64 import b64encode
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.lm_provider import ollama_keep_alive


DEFAULT_VISION_PROMPT = (
    "You are Odin's vision system. Describe what the camera sees in one or two "
    "concise sentences, focusing on the person, their expression, and anything "
    "notable in the scene."
)

DEFAULT_SCREEN_PROMPT = (
    "You are Odin's screen awareness. Describe what is currently on the user's "
    "screen in two or three concise sentences: the app in focus, what the user "
    "appears to be working on, and any notable dialogs or errors."
)


def capture_screen(screencapture_executable: str = "screencapture") -> bytes:
    """Capture the main display to JPEG bytes via macOS ``screencapture -x``.

    Requires the Screen Recording privacy permission; without it macOS returns
    a desktop-wallpaper-only image or an error, so the failure message points
    the user at System Settings."""
    with tempfile.TemporaryDirectory() as temporary_dir:
        target = Path(temporary_dir) / "screen.jpg"
        result = subprocess.run(
            [screencapture_executable, "-x", "-t", "jpg", str(target)],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )
        if result.returncode != 0 or not target.is_file():
            raise RuntimeError(
                (result.stderr or "").strip()
                or "Screen capture failed — grant O.D.I.N. Screen Recording "
                "access in System Settings → Privacy & Security."
            )
        return target.read_bytes()

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def mime_for_suffix(suffix: str) -> str:
    return _MIME_BY_SUFFIX.get(suffix.lower(), "image/jpeg")


class VisionState(StrEnum):
    IDLE = "idle"
    ANALYZING = "analyzing"


class VisionAdapter(Protocol):
    name: str
    configured: bool

    def analyze(self, image_path: Path, prompt: str) -> str:
        raise NotImplementedError


class UnconfiguredVisionAdapter:
    name = "unconfigured"
    configured = False

    def analyze(self, image_path: Path, prompt: str) -> str:
        raise RuntimeError("Vision adapter is not configured")


class CommandVisionAdapter:
    """Runs an external command that prints a description for an image."""

    name = "vision-command"
    configured = True

    def __init__(self, command: str) -> None:
        self.command = command

    def analyze(self, image_path: Path, prompt: str) -> str:
        if not image_path.is_file():
            raise RuntimeError(f"Image file not found: {image_path}")
        command = self.command.format(
            image_path=shlex.quote(str(image_path)),
            prompt=shlex.quote(prompt),
        )
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            shell=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Vision command failed")
        description = result.stdout.strip()
        if not description:
            raise RuntimeError("Vision command returned no text")
        return description


class OllamaVisionAdapter:
    """Multimodal description through a local Ollama vision model (e.g. llava)."""

    name = "ollama-vision"
    configured = True

    def __init__(
        self,
        model: str = "llava",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 120.0,
        keep_alive: str | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        # Vision calls are occasional while the chat model needs the RAM
        # constantly, so callers may pass "0" to evict the VLM right after each
        # analysis instead of the shared keep-alive window.
        self.keep_alive = ollama_keep_alive() if keep_alive is None else keep_alive

    @classmethod
    def available(cls, base_url: str, model: str, timeout_seconds: float = 5.0) -> bool:
        request = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return False
        names = [str(item.get("name") or item.get("model") or "") for item in body.get("models", [])]
        return any(name == model or name.startswith(f"{model}:") for name in names)

    def analyze(self, image_path: Path, prompt: str) -> str:
        if not image_path.is_file():
            raise RuntimeError(f"Image file not found: {image_path}")
        encoded = b64encode(image_path.read_bytes()).decode("ascii")
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt, "images": [encoded]}],
                "stream": False,
                "keep_alive": self.keep_alive,
                # Thinking-capable models (qwen3.5) reason for ~30s per frame
                # when left on; a frame description doesn't need it. Models
                # without thinking accept and ignore the flag.
                "think": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama vision request failed: {exc}") from exc
        try:
            description = str(body["message"]["content"]).strip()
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Ollama returned an unexpected vision response") from exc
        if not description:
            raise RuntimeError("Ollama vision returned no text")
        return description


class GeminiVisionAdapter:
    """Image description through Google Gemini's multimodal endpoint."""

    name = "gemini-vision"
    configured = True

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout_seconds: float = 45.0,
    ) -> None:
        cleaned = api_key.strip()
        if not cleaned:
            raise ValueError("A Gemini API key is required")
        self.api_key = cleaned
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def analyze(self, image_path: Path, prompt: str) -> str:
        if not image_path.is_file():
            raise RuntimeError(f"Image file not found: {image_path}")
        encoded = b64encode(image_path.read_bytes()).decode("ascii")
        payload = json.dumps(
            {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": mime_for_suffix(image_path.suffix),
                                    "data": encoded,
                                }
                            },
                        ],
                    }
                ]
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1beta/models/{self.model}:generateContent",
            data=payload,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini vision request failed: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Gemini vision request failed: {exc}") from exc
        try:
            parts = body["candidates"][0]["content"]["parts"]
            description = "".join(part.get("text", "") for part in parts).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Gemini returned an unexpected vision response") from exc
        if not description:
            raise RuntimeError("Gemini vision returned an empty response")
        return description


@dataclass(frozen=True, slots=True)
class VisionStatus:
    state: VisionState
    adapter: str
    configured: bool


class VisionManager:
    def __init__(
        self,
        adapter: VisionAdapter | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.state = VisionState.IDLE
        self.adapter = adapter or UnconfiguredVisionAdapter()
        self.event_bus = event_bus

    def transition(self, state: VisionState) -> None:
        self.state = state
        if self.event_bus is not None:
            self.event_bus.publish("vision.state", {"state": state.value})

    def status(self) -> VisionStatus:
        return VisionStatus(
            state=self.state,
            adapter=self.adapter.name,
            configured=self.adapter.configured,
        )

    def analyze(self, image_path: Path | str, prompt: str | None = None) -> str:
        self.transition(VisionState.ANALYZING)
        try:
            return self.adapter.analyze(Path(image_path), prompt or DEFAULT_VISION_PROMPT)
        finally:
            self.transition(VisionState.IDLE)

    def analyze_image(
        self, image: bytes, suffix: str = ".jpg", prompt: str | None = None
    ) -> str:
        if not image:
            raise RuntimeError("Image data is required")
        safe_suffix = suffix if suffix.startswith(".") and len(suffix) <= 10 else ".jpg"
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=safe_suffix, delete=False) as handle:
                handle.write(image)
                path = Path(handle.name)
            return self.analyze(path, prompt)
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
