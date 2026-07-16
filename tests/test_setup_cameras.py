from __future__ import annotations

import unittest

from scripts.setup_cameras import (
    build_url,
    candidate_paths,
    parse_ports,
    probe_ok,
    redact_url,
)


class SetupCamerasTests(unittest.TestCase):
    def test_build_url_encodes_credentials(self) -> None:
        url = build_url("192.168.1.50", 554, "admin", "p@ss:word", "/ch01/0")
        # The '@' and ':' in the password must be percent-encoded, not break the URL.
        self.assertEqual(url, "rtsp://admin:p%40ss%3Aword@192.168.1.50:554/ch01/0")

    def test_build_url_without_credentials(self) -> None:
        self.assertEqual(
            build_url("10.0.0.4", 554, "", "", "/live/ch01"),
            "rtsp://10.0.0.4:554/live/ch01",
        )

    def test_candidate_paths_are_channel_and_stream_aware(self) -> None:
        main = candidate_paths(1, substream=False)
        sub = candidate_paths(1, substream=True)
        self.assertIn("/ch01/0", main)
        self.assertIn("/ch01/1", sub)
        # Hikvision-style id is channel*100 + 1 (main) / 2 (sub).
        self.assertIn("/Streaming/Channels/101", main)
        self.assertIn("/Streaming/Channels/102", sub)
        self.assertIn("/ch02/0", candidate_paths(2, substream=False))

    def test_redact_url_hides_password(self) -> None:
        redacted = redact_url("rtsp://admin:secret@192.168.1.50:554/ch01/0")
        self.assertNotIn("secret", redacted)
        self.assertIn("192.168.1.50:554", redacted)

    def test_parse_ports_handles_lists_and_junk(self) -> None:
        self.assertEqual(parse_ports("554,5000"), [554, 5000])
        self.assertEqual(parse_ports("5000"), [5000])
        self.assertEqual(parse_ports("554, 554 , x"), [554])  # dedupe + skip junk
        self.assertEqual(parse_ports(""), [554])  # sensible fallback

    def test_probe_ok_requires_success_and_video(self) -> None:
        self.assertTrue(probe_ok(0, "codec_type=video\n"))
        self.assertFalse(probe_ok(0, "codec_type=audio\n"))
        self.assertFalse(probe_ok(1, "codec_type=video\n"))


if __name__ == "__main__":
    unittest.main()
