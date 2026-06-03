from __future__ import annotations

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
    def transcribe(self, audio_path: Path) -> str:
        raise NotImplementedError


class TextToSpeechAdapter(Protocol):
    def synthesize(self, text: str, voice_name: str | None = None) -> Path:
        raise NotImplementedError


class UnconfiguredSpeechToTextAdapter:
    def transcribe(self, audio_path: Path) -> str:
        raise RuntimeError("Speech-to-text adapter is not configured")


class UnconfiguredTextToSpeechAdapter:
    def synthesize(self, text: str, voice_name: str | None = None) -> Path:
        raise RuntimeError("Text-to-speech adapter is not configured")


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

    def transcribe(self, audio_path: Path | str) -> str:
        self.transition(VoiceState.THINKING)
        return self.stt_adapter.transcribe(Path(audio_path))

    def synthesize(self, text: str, voice_name: str | None = None) -> Path:
        self.transition(VoiceState.SPEAKING)
        return self.tts_adapter.synthesize(text, voice_name)

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
