from __future__ import annotations

import json
import shlex
import subprocess
import urllib.error
import urllib.request
from base64 import b64decode
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from jarvis.backend.core.event_bus import EventBus


# A 1x1 transparent PNG. The stub adapter returns this so the rest of the
# pipeline (save -> serve -> render) can be exercised with no model installed.
_STUB_PNG = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


class ImageState(StrEnum):
    IDLE = "idle"
    GENERATING = "generating"


class ImageAdapter(Protocol):
    name: str
    configured: bool
    # True when generation leaves the machine (cloud), so the bot can require
    # the network permission before running it.
    network: bool

    def generate(self, prompt: str) -> bytes:
        raise NotImplementedError


class UnconfiguredImageAdapter:
    name = "unconfigured"
    configured = False
    network = False

    def generate(self, prompt: str) -> bytes:
        raise RuntimeError(
            "Image generation is not set up. Enable turbo mode with a Gemini API "
            "key, or configure a local generator via JARVIS_IMAGE_COMMAND."
        )


class StubImageAdapter:
    """Returns a fixed tiny PNG. For tests and offline plumbing checks only."""

    name = "stub"
    configured = True
    network = False

    def generate(self, prompt: str) -> bytes:
        if not prompt.strip():
            raise RuntimeError("An image prompt is required")
        return _STUB_PNG


class CommandImageAdapter:
    """Runs a local command that writes a PNG for a prompt.

    The command template receives {prompt} and {output_path}; the command must
    write the image to {output_path}. This is the seam for a local Stable
    Diffusion / ComfyUI generator later — no other code changes when migrating
    off the cloud.
    """

    name = "image-command"
    configured = True
    network = False

    def __init__(self, command: str) -> None:
        self.command = command

    def generate(self, prompt: str) -> bytes:
        if not prompt.strip():
            raise RuntimeError("An image prompt is required")
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            command = self.command.format(
                prompt=shlex.quote(prompt),
                output_path=shlex.quote(str(output_path)),
            )
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                shell=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Image command failed")
            data = output_path.read_bytes()
            if not data:
                raise RuntimeError("Image command produced no image")
            return data
        finally:
            output_path.unlink(missing_ok=True)


class GeminiImageAdapter:
    """Image generation through Google Gemini's multimodal endpoint (cloud)."""

    name = "gemini-image"
    configured = True
    network = True

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash-preview-image-generation",
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout_seconds: float = 60.0,
    ) -> None:
        cleaned = api_key.strip()
        if not cleaned:
            raise ValueError("A Gemini API key is required")
        self.api_key = cleaned
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: str) -> bytes:
        if not prompt.strip():
            raise RuntimeError("An image prompt is required")
        payload = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
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
            raise RuntimeError(f"Gemini image request failed: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Gemini image request failed: {exc}") from exc
        try:
            parts = body["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Gemini returned an unexpected image response") from exc
        for part in parts:
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and str(inline.get("mime_type") or inline.get("mimeType", "")).startswith(
                "image/"
            ):
                data = inline.get("data")
                if data:
                    return b64decode(data)
        raise RuntimeError("Gemini did not return an image (it may have refused the prompt)")


@dataclass(frozen=True, slots=True)
class ImageStatus:
    state: ImageState
    adapter: str
    configured: bool
    network: bool


class ImageManager:
    def __init__(
        self,
        adapter: ImageAdapter | None = None,
        output_dir: Path | str = "data/images",
        event_bus: EventBus | None = None,
        max_files: int = 50,
    ) -> None:
        self.state = ImageState.IDLE
        self.adapter = adapter or UnconfiguredImageAdapter()
        self.output_dir = Path(output_dir)
        self.event_bus = event_bus
        self.max_files = max_files

    def transition(self, state: ImageState) -> None:
        self.state = state
        if self.event_bus is not None:
            self.event_bus.publish("image.state", {"state": state.value})

    def status(self) -> ImageStatus:
        return ImageStatus(
            state=self.state,
            adapter=self.adapter.name,
            configured=self.adapter.configured,
            network=getattr(self.adapter, "network", False),
        )

    def generate(self, prompt: str) -> Path:
        cleaned = (prompt or "").strip()
        if not cleaned:
            raise RuntimeError("An image prompt is required")
        self.transition(ImageState.GENERATING)
        try:
            data = self.adapter.generate(cleaned)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            path = self.output_dir / f"{uuid4().hex}.png"
            path.write_bytes(data)
            self._prune()
            return path
        finally:
            self.transition(ImageState.IDLE)

    def _prune(self) -> None:
        """Keep only the newest max_files images so the dir can't grow forever."""
        images = sorted(
            self.output_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for stale in images[self.max_files :]:
            stale.unlink(missing_ok=True)
