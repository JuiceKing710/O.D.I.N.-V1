"""Discover working RTSP URLs on an NVR and write data/cameras.json.

NVR brands (ZOSI, Reolink, Amcrest, Hikvision, Dahua, generic ONVIF) all expose
RTSP but disagree on the URL path, and the exact path varies by model/firmware.
Rather than guess, this probes each channel with the common path patterns using
ffprobe and keeps the first that returns a video stream, then writes the config
Odin's security monitor reads.

Run it on the machine that can reach the NVR (you must be on the same LAN):

    PYTHONPATH=. .venv/bin/python scripts/setup_cameras.py --ip 192.168.1.50 --channels 8

It will prompt for the NVR username/password (the password is never echoed and
is written only to the local data/cameras.json). Prefer the sub-stream (lighter)
for continuous monitoring, which is the default; pass --main for full-res.
"""
from __future__ import annotations

import argparse
import getpass
import json
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit


def redact_url(url: str) -> str:
    """Hide any user:pass in a URL so it is safe to print."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<url>"
    if not parts.hostname:
        return url
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    netloc = f"***@{host}" if (parts.username or parts.password) else host
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))


def candidate_paths(channel: int, substream: bool) -> list[str]:
    """Common RTSP path patterns for a 1-based channel, most-likely first.

    ``substream`` picks the lighter secondary stream where a brand distinguishes
    it. Patterns cover ZOSI and the OEM stacks ZOSI ships (Dahua/Hikvision-like)
    plus a few generic forms.
    """
    stream = 1 if substream else 0
    subtype = 1 if substream else 0
    ch2 = f"{channel:02d}"
    hik = channel * 100 + (2 if substream else 1)
    return [
        f"/ch{ch2}/{stream}",  # ZOSI / many OEM NVRs, e.g. ch01/0
        f"/cam/realmonitor?channel={channel}&subtype={subtype}",  # Dahua-style
        f"/Streaming/Channels/{hik}",  # Hikvision-style (ch*100 + 1/2)
        f"/live/ch{ch2}",
        f"/h264/ch{channel}/{'sub' if substream else 'main'}/av_stream",
        f"/mode=real&idc=1&ids={channel}",
    ]


def build_url(ip: str, port: int, user: str, password: str, path: str) -> str:
    """Assemble an rtsp:// URL, URL-encoding credentials for @/: safety."""
    creds = ""
    if user:
        creds = quote(user, safe="")
        if password:
            creds += f":{quote(password, safe='')}"
        creds += "@"
    sep = "" if path.startswith("/") else "/"
    return f"rtsp://{creds}{ip}:{port}{sep}{path}"


def probe_ok(returncode: int, stdout: str) -> bool:
    """A probe succeeded when ffprobe exited 0 and reported a video stream."""
    return returncode == 0 and "video" in stdout.lower()


def probe_url(url: str, ffprobe: str = "ffprobe", timeout: float = 8.0) -> bool:
    command = [
        ffprobe,
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-rw_timeout",
        str(int(timeout * 1_000_000)),  # microseconds
        "-i",
        url,
        "-show_entries",
        "stream=codec_type",
        "-of",
        "default=nw=1",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout + 4
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return probe_ok(result.returncode, result.stdout)


def discover_channel(
    ip: str,
    port: int,
    user: str,
    password: str,
    channel: int,
    substream: bool,
    ffprobe: str,
    timeout: float,
) -> str | None:
    for path in candidate_paths(channel, substream):
        url = build_url(ip, port, user, password, path)
        print(f"  channel {channel}: trying {redact_url(url)} … ", end="", flush=True)
        if probe_url(url, ffprobe=ffprobe, timeout=timeout):
            print("OK")
            return url
        print("no")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover NVR RTSP URLs for Odin.")
    parser.add_argument("--ip", required=True, help="NVR IP address on your LAN")
    parser.add_argument("--port", type=int, default=554, help="RTSP port (default 554)")
    parser.add_argument("--channels", type=int, default=8, help="Number of cameras/channels")
    parser.add_argument("--user", default=None, help="NVR username (prompted if omitted)")
    parser.add_argument(
        "--password", default=None, help="NVR password (prompted, hidden, if omitted)"
    )
    parser.add_argument(
        "--main", action="store_true", help="Use the full-res main stream (default: sub-stream)"
    )
    parser.add_argument("--ffprobe", default="ffprobe", help="ffprobe binary")
    parser.add_argument("--timeout", type=float, default=8.0, help="Per-probe timeout (s)")
    parser.add_argument(
        "--output", default="data/cameras.json", help="Where to write the config"
    )
    args = parser.parse_args()

    user = args.user if args.user is not None else input("NVR username: ").strip()
    password = args.password if args.password is not None else getpass.getpass("NVR password: ")
    substream = not args.main

    print(f"\nProbing {args.channels} channel(s) on {args.ip}:{args.port} "
          f"({'sub' if substream else 'main'} stream)…\n")
    cameras = []
    for channel in range(1, args.channels + 1):
        url = discover_channel(
            args.ip, args.port, user, password, channel, substream, args.ffprobe, args.timeout
        )
        if url:
            cameras.append({"name": f"Camera {channel}", "url": url})
        else:
            print(f"  channel {channel}: no working URL found — skipping")

    if not cameras:
        print(
            "\nNo streams found. Check that the NVR is on the LAN, RTSP/ONVIF is "
            "enabled in its network settings, the IP/port/credentials are right, "
            "and ffprobe is installed (`brew install ffmpeg`)."
        )
        return 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cameras, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {len(cameras)} camera(s) to {output}.")
    print("Rename them by editing that file, then start Odin with "
          "JARVIS_SECURITY_MONITOR=enabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
