from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jarvis.backend.core.camera_monitor import (
    CameraMonitor,
    build_detection_prompt,
    verdict_from_description,
)
from jarvis.backend.core.camera_source import (
    RTSPCameraSource,
    UnconfiguredCameraSource,
    redact_url,
)
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.notifier import NtfyNotifier, UnconfiguredNotifier
from jarvis.backend.core.vision_manager import VisionManager


class _FakeVisionAdapter:
    name = "fake-vision"
    configured = True

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def analyze(self, image_path, prompt):
        self.prompts.append(prompt)
        return self.reply


class _FakeCamera:
    configured = True

    def __init__(self, name: str, frame: bytes = b"jpegframe", error: str | None = None) -> None:
        self.name = name
        self.frame = frame
        self.error = error
        self.grabs = 0

    def grab_frame(self) -> bytes:
        self.grabs += 1
        if self.error is not None:
            raise RuntimeError(self.error)
        return self.frame


class _RecordingNotifier:
    name = "recording"
    configured = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def notify(self, title: str, message: str, priority: str = "default") -> None:
        self.sent.append((title, message, priority))


class RedactionTests(unittest.TestCase):
    def test_strips_credentials_from_rtsp_url(self) -> None:
        redacted = redact_url("rtsp://admin:s3cret@192.168.1.50:554/ch01/0")
        self.assertNotIn("s3cret", redacted)
        self.assertNotIn("admin", redacted)
        self.assertIn("192.168.1.50:554", redacted)

    def test_url_without_credentials_is_unchanged_host(self) -> None:
        self.assertIn("10.0.0.4", redact_url("rtsp://10.0.0.4:554/stream"))


class VerdictTests(unittest.TestCase):
    def test_alert_prefix_extracts_summary(self) -> None:
        is_alert, summary = verdict_from_description("ALERT: a person is at the front door")
        self.assertTrue(is_alert)
        self.assertEqual(summary, "a person is at the front door")

    def test_clear_is_not_an_alert(self) -> None:
        self.assertEqual(verdict_from_description("CLEAR"), (False, ""))

    def test_empty_or_unformatted_reply_does_not_alert(self) -> None:
        self.assertEqual(verdict_from_description(""), (False, ""))
        self.assertEqual(verdict_from_description("the yard looks normal"), (False, ""))

    def test_prompt_lists_watched_items(self) -> None:
        prompt = build_detection_prompt(["a person", "a package"])
        self.assertIn("a person", prompt)
        self.assertIn("a package", prompt)
        self.assertIn("CLEAR", prompt)


class RTSPCameraSourceTests(unittest.TestCase):
    def test_grab_frame_returns_written_bytes(self) -> None:
        def fake_run(command, **kwargs):
            Path(command[-1]).write_bytes(b"jpeg-bytes")
            return SimpleNamespace(returncode=0, stderr="")

        source = RTSPCameraSource("Front", "rtsp://admin:pw@10.0.0.5:554/ch01/0")
        with mock.patch("jarvis.backend.core.camera_source.subprocess.run", fake_run):
            self.assertEqual(source.grab_frame(), b"jpeg-bytes")

    def test_failure_redacts_credentials_in_error(self) -> None:
        def fake_run(command, **kwargs):
            return SimpleNamespace(
                returncode=1, stderr="rtsp://admin:pw@10.0.0.5:554/ch01/0 refused"
            )

        source = RTSPCameraSource("Front", "rtsp://admin:pw@10.0.0.5:554/ch01/0")
        with mock.patch("jarvis.backend.core.camera_source.subprocess.run", fake_run):
            with self.assertRaises(RuntimeError) as ctx:
                source.grab_frame()
        self.assertNotIn("pw", str(ctx.exception))

    def test_unconfigured_source_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            UnconfiguredCameraSource("Back", "ffmpeg missing").grab_frame()


class NtfyNotifierTests(unittest.TestCase):
    def test_notify_posts_to_topic_with_headers(self) -> None:
        captured = {}

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b""

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["data"] = request.data
            captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
            return _Resp()

        notifier = NtfyNotifier(topic="odin-alerts", base_url="https://ntfy.sh")
        with mock.patch(
            "jarvis.backend.core.notifier.urllib.request.urlopen", fake_urlopen
        ):
            notifier.notify("Odin: Front", "a person at the door", priority="high")

        self.assertEqual(captured["url"], "https://ntfy.sh/odin-alerts")
        self.assertEqual(captured["data"], b"a person at the door")
        self.assertEqual(captured["headers"].get("priority"), "4")

    def test_unconfigured_notifier_is_noop(self) -> None:
        notifier = UnconfiguredNotifier()
        self.assertFalse(notifier.configured)
        self.assertIsNone(notifier.notify("t", "m"))


class CameraMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.capture_dir = Path(self.tmp.name) / "captures"

    def _monitor(self, vision_reply: str, camera: _FakeCamera, **kwargs) -> tuple:
        bus = EventBus()
        notifier = _RecordingNotifier()
        vision = VisionManager(adapter=_FakeVisionAdapter(vision_reply))
        monitor = CameraMonitor(
            [camera],
            vision,
            event_bus=bus,
            notifier=notifier,
            capture_dir=self.capture_dir,
            enabled=True,
            **kwargs,
        )
        return monitor, bus, notifier

    def test_alert_publishes_event_notifies_and_saves_capture(self) -> None:
        camera = _FakeCamera("Front Door")
        monitor, bus, notifier = self._monitor("ALERT: a stranger on the porch", camera)

        alerts = asyncio.run(monitor.scan_all())

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].camera, "Front Door")
        self.assertEqual(alerts[0].summary, "a stranger on the porch")
        alert_events = [e for e in bus.history() if e.type == "security.alert"]
        self.assertEqual(len(alert_events), 1)
        self.assertEqual(len(notifier.sent), 1)
        self.assertEqual(notifier.sent[0][2], "high")
        # The triggering frame is saved and exposed as an image_url.
        self.assertTrue(alerts[0].to_api()["image_url"].startswith("/api/v1/security/capture/"))
        self.assertTrue(any(self.capture_dir.glob("*.jpg")))

    def test_clear_scene_raises_no_alert(self) -> None:
        camera = _FakeCamera("Yard")
        monitor, bus, notifier = self._monitor("CLEAR", camera)

        self.assertEqual(asyncio.run(monitor.scan_all()), [])
        self.assertEqual([e for e in bus.history() if e.type == "security.alert"], [])
        self.assertEqual(notifier.sent, [])

    def test_cooldown_suppresses_repeat_alert(self) -> None:
        camera = _FakeCamera("Drive")
        monitor, _bus, notifier = self._monitor(
            "ALERT: a car in the driveway", camera, cooldown_seconds=3600
        )

        first = asyncio.run(monitor.scan_all())
        second = asyncio.run(monitor.scan_all())

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])  # within cooldown → silent
        self.assertEqual(len(notifier.sent), 1)

    def test_bad_camera_does_not_stop_the_sweep(self) -> None:
        good = _FakeCamera("Good")
        bad = _FakeCamera("Bad", error="stream refused")
        bus = EventBus()
        vision = VisionManager(adapter=_FakeVisionAdapter("ALERT: motion"))
        monitor = CameraMonitor(
            [bad, good],
            vision,
            event_bus=bus,
            notifier=_RecordingNotifier(),
            capture_dir=self.capture_dir,
            enabled=True,
        )

        alerts = asyncio.run(monitor.scan_all())

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].camera, "Good")
        statuses = {c["name"]: c for c in monitor.status()["cameras"]}
        self.assertIn("stream refused", statuses["Bad"]["last_error"])

    def test_status_reports_configuration(self) -> None:
        camera = _FakeCamera("Front")
        monitor, _bus, _notifier = self._monitor(
            "CLEAR", camera, watch_for=["a person"], interval_seconds=15
        )
        status = monitor.status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["interval_seconds"], 15)
        self.assertEqual(status["watch_for"], ["a person"])
        self.assertEqual(status["cameras"][0]["name"], "Front")

    def test_disabled_monitor_does_not_start(self) -> None:
        camera = _FakeCamera("Front")
        vision = VisionManager(adapter=_FakeVisionAdapter("CLEAR"))
        monitor = CameraMonitor(
            [camera], vision, capture_dir=self.capture_dir, enabled=False
        )

        async def run() -> bool:
            monitor.start()
            running = monitor.status()["running"]
            await monitor.stop()
            return running

        self.assertFalse(asyncio.run(run()))


if __name__ == "__main__":
    unittest.main()
