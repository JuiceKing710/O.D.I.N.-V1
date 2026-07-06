from __future__ import annotations

import logging
import re
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

logger = logging.getLogger(__name__)

# Real speech peaks around -3 dB; a silent/muted mic floors near -90 dB and a
# quiet but speechless room sits around -60 dB. -45 dB cleanly separates them.
SILENCE_MAX_DB = -45.0

_MAX_VOLUME_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")

# Whisper hallucinates filler on silence: bracketed markers like "[BLANK_AUDIO]"
# or "[ Silence ]", or a lone stray word. These are not speech and must never be
# forwarded to the language model as if the user had said them.
_BLANK_TRANSCRIPT_RE = re.compile(r"^[\[(][^\])]*[\])][.\s]*$")


def _audio_peak_db(ffmpeg_stderr: str) -> float | None:
    """Parse the peak volume (dB) from ffmpeg ``volumedetect`` stderr output.

    Returns ``None`` when no measurement is present so callers can fail open
    rather than wrongly reject audio they could not measure."""
    match = _MAX_VOLUME_RE.search(ffmpeg_stderr or "")
    return float(match.group(1)) if match else None


def _is_blank_transcript(transcript: str) -> bool:
    cleaned = transcript.strip()
    return not cleaned or bool(_BLANK_TRANSCRIPT_RE.match(cleaned))


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


class WhisperCliSpeechToTextAdapter:
    name = "whisper-cli"

    def __init__(
        self,
        executable: str,
        model_path: Path | str,
        ffmpeg_executable: str,
        use_gpu: bool = True,
    ) -> None:
        self.executable = executable
        self.model_path = Path(model_path)
        self.ffmpeg_executable = ffmpeg_executable
        # On Apple Silicon, Metal roughly halves transcription latency and moves
        # the work off the CPU cores. Disabled via JARVIS_WHISPER_GPU for hosts
        # where GPU init is unreliable or unified memory is too tight.
        self.use_gpu = use_gpu

    @property
    def configured(self) -> bool:
        return self.model_path.is_file() and self.model_path.stat().st_size > 1_000_000

    def transcribe_command(self, wav_path: Path) -> list[str]:
        command = [
            self.executable,
            "-m",
            str(self.model_path),
            "-f",
            str(wav_path),
            "-np",
            "-nt",
            "-l",
            "en",
        ]
        if not self.use_gpu:
            command.append("-ng")
        return command

    def transcribe(self, audio_path: Path) -> str:
        if not self.configured:
            raise RuntimeError(f"Whisper model is missing or invalid: {self.model_path}")
        with tempfile.TemporaryDirectory() as temporary_dir:
            wav_path = Path(temporary_dir) / "input.wav"
            converted = subprocess.run(
                [
                    self.ffmpeg_executable,
                    "-y",
                    "-i",
                    str(audio_path),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-af",
                    "volumedetect",
                    str(wav_path),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=120,
            )
            if converted.returncode != 0 or not wav_path.is_file():
                raise RuntimeError(converted.stderr.strip() or "Audio conversion failed")
            # Reject silence before transcription: a muted mic, denied OS
            # permission, or the wrong input device records near-total silence,
            # which Whisper "transcribes" into hallucinated filler. Catching it
            # here gives the user a clear "no speech" error instead of letting a
            # phantom phrase reach the language model.
            peak_db = _audio_peak_db(converted.stderr)
            logger.info("Audio peak volume: %s dB (silence gate %s dB)", peak_db, SILENCE_MAX_DB)
            if peak_db is not None and peak_db < SILENCE_MAX_DB:
                raise RuntimeError(
                    "No speech detected — the microphone captured silence. "
                    "Check that the right input device is selected and that "
                    "O.D.I.N. has microphone access in System Settings."
                )
            result = subprocess.run(
                self.transcribe_command(wav_path),
                capture_output=True,
                check=False,
                text=True,
                timeout=180,
            )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Local Whisper transcription failed")
        transcript = result.stdout.strip()
        if _is_blank_transcript(transcript):
            logger.info("Discarded blank/hallucinated transcript: %r", transcript)
            raise RuntimeError("No speech detected in the audio")
        logger.info("Transcribed %d chars of speech", len(transcript))
        return transcript


class PiperTextToSpeechAdapter:
    """Neural text-to-speech through a local Piper voice model."""

    name = "piper"
    configured = True

    def __init__(self, piper_binary: str, model_path: Path | str, output_dir: Path | str) -> None:
        self.piper_binary = piper_binary
        self.model_path = Path(model_path)
        self.output_dir = Path(output_dir)

    @classmethod
    def available(cls, piper_binary: str | None, model_path: Path) -> bool:
        return bool(piper_binary) and model_path.is_file()

    def synthesize(self, text: str, voice_name: str | None = None) -> Path:
        cleaned = text.strip()
        if not cleaned:
            raise RuntimeError("Text is required for speech synthesis")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target = self.output_dir / f"jarvis-{uuid.uuid4().hex}.wav"
        result = subprocess.run(
            [self.piper_binary, "-m", str(self.model_path), "-f", str(target)],
            input=cleaned,
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        if result.returncode != 0 or not target.is_file():
            raise RuntimeError(result.stderr.strip() or "Piper speech synthesis failed")
        return target


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
        fallback_tts_adapter: TextToSpeechAdapter | None = None,
    ) -> None:
        self.state = VoiceState.IDLE
        self.interruption_config = interruption_config or InterruptionConfig()
        self.stt_adapter = stt_adapter or UnconfiguredSpeechToTextAdapter()
        self.tts_adapter = tts_adapter or UnconfiguredTextToSpeechAdapter()
        self.event_bus = event_bus
        self._fallback_tts = fallback_tts_adapter
        self.last_tts_fallback: str | None = None
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
            output = self._synthesize_with_fallback(text, voice_name)
            self._prune_voice_outputs(output)
            return output
        finally:
            self.transition(VoiceState.IDLE)

    def _synthesize_with_fallback(self, text: str, voice_name: str | None) -> Path:
        """Try the configured adapter; if it fails for any reason (e.g. a broken
        Piper binary), degrade to native macOS say rather than crashing."""
        self.last_tts_fallback = None
        try:
            return self.tts_adapter.synthesize(text, voice_name)
        except Exception as primary_error:  # noqa: BLE001 - any failure should degrade, not 500
            # Only rescue an adapter that claimed to be ready but failed at
            # runtime (e.g. broken Piper). The Unconfigured placeholder is a
            # deliberate "nothing set up" state and must keep surfacing as such.
            if not getattr(self.tts_adapter, "configured", False):
                raise
            fallback = self._ensure_fallback_tts()
            if fallback is None:
                raise
            self.last_tts_fallback = (
                f"{self.tts_adapter.name} failed ({primary_error}); used {fallback.name}"
            )
            if self.event_bus is not None:
                self.event_bus.publish(
                    "voice.tts_fallback",
                    {"primary": self.tts_adapter.name, "fallback": fallback.name},
                    transient=True,
                )
            return fallback.synthesize(text, voice_name)

    def _ensure_fallback_tts(self) -> TextToSpeechAdapter | None:
        if self._fallback_tts is not None:
            return self._fallback_tts
        # Native say is the universal fallback on macOS; never fall back say->say.
        if isinstance(self.tts_adapter, MacOSTextToSpeechAdapter) or not MacOSTextToSpeechAdapter.available():
            return None
        output_dir = getattr(self.tts_adapter, "output_dir", None) or (
            Path(tempfile.gettempdir()) / "jarvis-voice"
        )
        self._fallback_tts = MacOSTextToSpeechAdapter(output_dir)
        return self._fallback_tts

    def _prune_voice_outputs(self, current: Path, keep: int = 20) -> None:
        output_dir = getattr(self.tts_adapter, "output_dir", None)
        if output_dir is None:
            return
        files = sorted(
            (path for path in Path(output_dir).glob("jarvis-*") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in files[keep:]:
            if stale != current:
                stale.unlink(missing_ok=True)

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
