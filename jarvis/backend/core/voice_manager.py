from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from jarvis.backend.core.event_bus import EventBus


class VoiceState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass(slots=True)
class InterruptionConfig:
    energy_threshold: float = 0.65
    hold_frames: int = 3
    release_frames: int = 8


class SpeechToTextAdapter(Protocol):
    name: str
    configured: bool

    def transcribe(self, audio_path: Path) -> str:
        raise NotImplementedError


class TextToSpeechAdapter(Protocol):
    name: str
    configured: bool

    def synthesize(self, text: str, voice_name: str | None = None) -> Path:
        raise NotImplementedError


class UnconfiguredSpeechToTextAdapter:
    name = "unconfigured"
    configured = False

    def transcribe(self, audio_path: Path) -> str:
        raise RuntimeError("Speech-to-text adapter is not configured")


class UnconfiguredTextToSpeechAdapter:
    name = "unconfigured"
    configured = False

    def synthesize(self, text: str, voice_name: str | None = None) -> Path:
        raise RuntimeError("Text-to-speech adapter is not configured")


class WhisperCommandSpeechToTextAdapter:
    name = "whisper-command"
    configured = True

    def __init__(self, command: str) -> None:
        self.command = command

    def transcribe(self, audio_path: Path) -> str:
        if not audio_path.is_file():
            raise RuntimeError(f"Audio file not found: {audio_path}")
        command = self.command.format(audio_path=shlex.quote(str(audio_path)))
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            shell=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Whisper transcription failed")
        transcript = result.stdout.strip()
        if not transcript:
            raise RuntimeError("Whisper transcription returned no text")
        return transcript


class MacOSTextToSpeechAdapter:
    name = "macos-say"
    configured = True

    def __init__(self, output_dir: Path | str) -> None:
        self.output_dir = Path(output_dir)

    @classmethod
    def available(cls) -> bool:
        return shutil.which("say") is not None

    def synthesize(self, text: str, voice_name: str | None = None) -> Path:
        cleaned = text.strip()
        if not cleaned:
            raise RuntimeError("Text is required for speech synthesis")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        identifier = uuid.uuid4().hex
        source = self.output_dir / f"jarvis-{identifier}.aiff"
        target = self.output_dir / f"jarvis-{identifier}.wav"
        command = ["say", "-o", str(source)]
        if voice_name:
            command.extend(["-v", voice_name])
        command.append(cleaned)
        result = subprocess.run(command, capture_output=True, check=False, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "macOS speech synthesis failed")
        try:
            result = subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16", str(source), str(target)],
                capture_output=True,
                check=False,
                text=True,
                timeout=120,
            )
        finally:
            source.unlink(missing_ok=True)
        if result.returncode != 0 or not target.is_file():
            raise RuntimeError(result.stderr.strip() or "macOS audio conversion failed")
        return target


class CommandTextToSpeechAdapter:
    name = "tts-command"
    configured = True

    def __init__(self, command: str, output_dir: Path | str) -> None:
        self.command = command
        self.output_dir = Path(output_dir)

    def synthesize(self, text: str, voice_name: str | None = None) -> Path:
        cleaned = text.strip()
        if not cleaned:
            raise RuntimeError("Text is required for speech synthesis")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target = self.output_dir / f"jarvis-{uuid.uuid4().hex}.wav"
        command = self.command.format(
            output_path=shlex.quote(str(target)),
            text=shlex.quote(cleaned),
            voice_name=shlex.quote(voice_name or ""),
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
            raise RuntimeError(result.stderr.strip() or "Speech synthesis command failed")
        if not target.is_file():
            raise RuntimeError(f"Speech synthesis did not create output: {target}")
        return target


@dataclass(frozen=True, slots=True)
class VoiceStatus:
    state: VoiceState
    stt_adapter: str
    stt_configured: bool
    tts_adapter: str
    tts_configured: bool


class VoiceManager:
    def __init__(
        self,
        interruption_config: InterruptionConfig | None = None,
        stt_adapter: SpeechToTextAdapter | None = None,
        tts_adapter: TextToSpeechAdapter | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.state = VoiceState.IDLE
        self.interruption_config = interruption_config or InterruptionConfig()
        self.stt_adapter = stt_adapter or UnconfiguredSpeechToTextAdapter()
        self.tts_adapter = tts_adapter or UnconfiguredTextToSpeechAdapter()
        self.event_bus = event_bus
        self._speech_frames = 0
        self._silence_frames = 0

    def transition(self, state: VoiceState) -> None:
        self.state = state
        if self.event_bus is not None:
            self.event_bus.publish("voice.state", {"state": state.value})

    def status(self) -> VoiceStatus:
        return VoiceStatus(
            state=self.state,
            stt_adapter=self.stt_adapter.name,
            stt_configured=self.stt_adapter.configured,
            tts_adapter=self.tts_adapter.name,
            tts_configured=self.tts_adapter.configured,
        )

    def transcribe(self, audio_path: Path | str) -> str:
        self.transition(VoiceState.THINKING)
        try:
            return self.stt_adapter.transcribe(Path(audio_path))
        finally:
            self.transition(VoiceState.IDLE)

    def transcribe_audio(self, audio: bytes, suffix: str = ".webm") -> str:
        if not audio:
            raise RuntimeError("Audio data is required")
        safe_suffix = suffix if suffix.startswith(".") and len(suffix) <= 10 else ".webm"
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=safe_suffix, delete=False) as handle:
                handle.write(audio)
                path = Path(handle.name)
            return self.transcribe(path)
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    def synthesize(self, text: str, voice_name: str | None = None) -> Path:
        self.transition(VoiceState.SPEAKING)
        try:
            return self.tts_adapter.synthesize(text, voice_name)
        finally:
            self.transition(VoiceState.IDLE)

    def detect_interruption(self, normalized_energy: float) -> bool:
        if self.state != VoiceState.SPEAKING:
            self._speech_frames = 0
            self._silence_frames = 0
            return False

        if normalized_energy >= self.interruption_config.energy_threshold:
            self._speech_frames += 1
            self._silence_frames = 0
        else:
            self._silence_frames += 1
            if self._silence_frames >= self.interruption_config.release_frames:
                self._speech_frames = 0

        return self._speech_frames >= self.interruption_config.hold_frames
