from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.security_monitor import (
    _SIGNATURE_SIZE,
    CameraConfig,
    SecurityMonitor,
    load_cameras,
    mean_abs_diff,
)
from jarvis.backend.core.vision_manager import VisionManager


class FakeVisionAdapter:
    name = "fake-vision"

    def __init__(self, configured: bool = True, description: str = "A person at the door.") -> None:
        self.configured = configured
        self.description = description
        self.calls = 0

    def analyze(self, image_path: Path, prompt: str) -> str:
        self.calls += 1
        return self.description


def _frame(value: int) -> bytes:
    return bytes([value]) * _SIGNATURE_SIZE


class LoadCamerasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(load_cameras(self.base / "nope.json"), [])

    def test_malformed_file_returns_empty(self) -> None:
        path = self.base / "cameras.json"
        path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(load_cameras(path), [])

    def test_parses_entries_and_defaults_names(self) -> None:
        path = self.base / "cameras.json"
        path.write_text(
            json.dumps(
                [
                    {"name": "Front Door", "url": "rtsp://x/1"},
                    {"url": "rtsp://x/2"},  # name defaulted
                    {"name": "no url"},  # skipped
                    "garbage",  # skipped
                ]
            ),
            encoding="utf-8",
        )
        cameras = load_cameras(path)
        self.assertEqual(
            cameras,
            [
                CameraConfig(name="Front Door", url="rtsp://x/1"),
                CameraConfig(name="Camera 2", url="rtsp://x/2"),
            ],
        )


class MeanAbsDiffTests(unittest.TestCase):
    def test_identical_is_zero(self) -> None:
        self.assertEqual(mean_abs_diff(_frame(10), _frame(10)), 0.0)

    def test_difference_is_absolute_mean(self) -> None:
        self.assertEqual(mean_abs_diff(_frame(10), _frame(60)), 50.0)

    def test_mismatched_length_is_zero(self) -> None:
        self.assertEqual(mean_abs_diff(b"abc", b"ab"), 0.0)


class SecurityMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory = MemoryManager(base / "jarvis.db")
        self.events = EventBus()
        self.adapter = FakeVisionAdapter()
        self.vision = VisionManager(adapter=self.adapter, event_bus=self.events)
        self.cameras_path = base / "cameras.json"
        self.cameras_path.write_text(
            json.dumps([{"name": "Front Door", "url": "rtsp://x/1"}]), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _monitor(self, frames: list[bytes], **kwargs) -> SecurityMonitor:
        queue = list(frames)

        def grab_sig(_url: str) -> bytes | None:
            return queue.pop(0) if queue else None

        return SecurityMonitor(
            self.vision,
            event_bus=self.events,
            memory=self.memory,
            cameras_path=self.cameras_path,
            enabled=False,
            signature_grabber=grab_sig,
            frame_grabber=lambda _url: b"jpeg-bytes",
            **kwargs,
        )

    def _event_types(self) -> list[str]:
        return [event.type for event in self.events.history()]

    def test_first_frame_is_baseline_no_alert(self) -> None:
        monitor = self._monitor([_frame(0)])
        summary = asyncio.run(monitor.tick())
        self.assertEqual(summary["checked"], 1)
        self.assertEqual(summary["motion"], [])
        self.assertEqual(summary["alerts"], [])
        self.assertEqual(self.adapter.calls, 0)

    def test_motion_triggers_alert_event_and_persistence(self) -> None:
        monitor = self._monitor([_frame(0), _frame(80)], motion_threshold=8.0)
        asyncio.run(monitor.tick())  # baseline
        summary = asyncio.run(monitor.tick())  # motion
        self.assertEqual(summary["motion"], ["Front Door"])
        self.assertEqual(len(summary["alerts"]), 1)
        self.assertEqual(summary["alerts"][0]["description"], "A person at the door.")
        self.assertEqual(self.adapter.calls, 1)
        self.assertIn("security.motion", self._event_types())
        self.assertIn("security.alert", self._event_types())
        # Persisted as a recallable security document.
        user = self.memory.get_or_create_user("local-user")
        sources = [doc.source for doc in self.memory.list_documents(user.user_id)]
        self.assertIn("security", sources)

    def test_below_threshold_is_not_motion(self) -> None:
        monitor = self._monitor([_frame(0), _frame(3)], motion_threshold=8.0)
        asyncio.run(monitor.tick())  # baseline
        summary = asyncio.run(monitor.tick())
        self.assertEqual(summary["motion"], [])
        self.assertEqual(self.adapter.calls, 0)

    def test_cooldown_suppresses_second_description(self) -> None:
        monitor = self._monitor(
            [_frame(0), _frame(80), _frame(150)], motion_threshold=8.0, cooldown_seconds=3600.0
        )
        asyncio.run(monitor.tick())  # baseline
        asyncio.run(monitor.tick())  # first motion -> alert
        summary = asyncio.run(monitor.tick())  # motion again, but cooled down
        self.assertEqual(summary["motion"], ["Front Door"])
        self.assertEqual(summary["alerts"], [])  # no new description
        self.assertEqual(self.adapter.calls, 1)  # VLM only ran once

    def test_grab_failure_counts_as_error(self) -> None:
        monitor = self._monitor([None])
        summary = asyncio.run(monitor.tick())
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["motion"], [])
        self.assertIsNotNone(monitor.last_error)

    def test_status_reports_camera_count_and_configured(self) -> None:
        monitor = self._monitor([_frame(0)])
        status = monitor.status()
        self.assertEqual(status.camera_count, 1)
        self.assertTrue(status.configured)  # cameras present + vision configured
        self.assertFalse(status.running)

    def test_status_unconfigured_when_vision_offline(self) -> None:
        self.adapter.configured = False
        monitor = self._monitor([_frame(0)])
        self.assertFalse(monitor.status().configured)


if __name__ == "__main__":
    unittest.main()
