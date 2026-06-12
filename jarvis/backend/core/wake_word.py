from __future__ import annotations

import asyncio
import functools
import threading
import time

from jarvis.backend.core.event_bus import EventBus


class WakeWordListener:
    """Listens to the microphone for a wake word and publishes voice.wake events.

    Runs openwakeword in a daemon thread; depends on the optional openwakeword
    and sounddevice packages and degrades to disabled when they are missing.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        *,
        model_name: str = "hey_jarvis",
        threshold: float = 0.5,
        cooldown_seconds: float = 3.0,
    ) -> None:
        self.event_bus = event_bus
        self.model_name = model_name
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.running = False
        self.last_error: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def start(self) -> None:
        if self._thread is not None:
            return
        try:
            import openwakeword  # noqa: F401
            import sounddevice  # noqa: F401
        except ImportError as exc:
            self.last_error = f"Wake word dependencies are not installed: {exc}"
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="jarvis-wake-word", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=3)
        self._thread = None
        self.running = False

    def status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "model": self.model_name,
            "last_error": self.last_error,
        }

    def _run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from openwakeword.model import Model

            model = Model(wakeword_models=[self.model_name], inference_framework="onnx")
            last_fired = 0.0
            with sd.InputStream(
                samplerate=16000, channels=1, dtype="int16", blocksize=1280
            ) as stream:
                self.running = True
                self.last_error = None
                while not self._stop.is_set():
                    frame, _overflowed = stream.read(1280)
                    scores = model.predict(np.squeeze(frame))
                    score = float(scores.get(self.model_name, 0.0))
                    now = time.monotonic()
                    if score >= self.threshold and now - last_fired > self.cooldown_seconds:
                        last_fired = now
                        self._publish(score)
        except Exception as exc:  # noqa: BLE001 - surfaced via status
            self.last_error = str(exc)
        finally:
            self.running = False

    def _publish(self, score: float) -> None:
        if self.event_bus is None or self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(
            functools.partial(
                self.event_bus.publish,
                "voice.wake",
                {"score": round(score, 3), "model": self.model_name},
                transient=True,
            )
        )
