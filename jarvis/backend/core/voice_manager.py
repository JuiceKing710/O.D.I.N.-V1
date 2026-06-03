from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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


class VoiceManager:
    def __init__(self, interruption_config: InterruptionConfig | None = None) -> None:
        self.state = VoiceState.IDLE
        self.interruption_config = interruption_config or InterruptionConfig()
        self._speech_frames = 0
        self._silence_frames = 0

    def transition(self, state: VoiceState) -> None:
        self.state = state

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

