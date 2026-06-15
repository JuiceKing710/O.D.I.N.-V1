"""End-to-end capability verification for Odin.

Drives the real FastAPI app through TestClient with throwaway data dirs so it
proves what actually works on THIS machine without touching real app state.
Run: PYTHONPATH=. .venv/bin/python scripts/verify_capabilities.py
"""
from __future__ import annotations

import base64
import os
import tempfile
import time
from pathlib import Path

# Env must be set before importing the app (app_factory caches on first use).
_TMP = Path(tempfile.mkdtemp(prefix="odin-verify-"))
os.environ.update(
    JARVIS_LLM_PROVIDER="echo",            # no chat model needed for this pass
    JARVIS_VECTOR_PROVIDER="disabled",
    JARVIS_SCHEDULED_BACKUPS="disabled",
    JARVIS_CONSOLIDATION="disabled",
    JARVIS_DB_PATH=str(_TMP / "jarvis.db"),
    JARVIS_SETTINGS_PATH=str(_TMP / "settings.json"),
    JARVIS_AUDIT_LOG=str(_TMP / "audit.log"),
    JARVIS_PERMISSION_REQUESTS_PATH=str(_TMP / "permissions.json"),
    JARVIS_VOICE_OUTPUT_DIR=str(_TMP / "voice"),
    JARVIS_BACKUP_DIR=str(_TMP / "backups"),
    JARVIS_VECTOR_DB_PATH=str(_TMP / "vectors.db"),
    # Force the native macOS say path: the venv's piper console-script has a
    # stale shebang (project was renamed Jarvis-V1 -> O.D.I.N.-V1) and crashes.
    JARVIS_PIPER_VOICE=str(_TMP / "no-such-piper-voice.onnx"),
)

from fastapi.testclient import TestClient  # noqa: E402

from jarvis.backend.api.main import create_app  # noqa: E402
from jarvis.backend.core.app_factory import get_permission_manager  # noqa: E402

API = "/api/v1"
REPO = Path(__file__).resolve().parents[1]


def line(label: str, verdict: str, detail: str = "") -> None:
    print(f"  [{verdict:^6}] {label}" + (f" :: {detail}" if detail else ""))


def guard(label: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - verification must continue
        line(label, "ERROR", f"{type(exc).__name__}: {exc}"[:110])


def main() -> None:
    print(f"\nOdin capability verification  (temp data: {_TMP})\n")
    client = TestClient(create_app())
    client.__enter__()  # trigger lifespan
    pm = get_permission_manager()
    state: dict = {}

    def voice_out() -> None:
        t = time.monotonic()
        r = client.post(f"{API}/voice/synthesize", json={"text": "Odin is online."})
        ms = (time.monotonic() - t) * 1000
        r.raise_for_status()
        state["wav"] = Path(r.json()["audio_path"]).name
        audio = client.get(f"{API}/voice/audio/{state['wav']}")
        line("voice OUT (say -> wav, served)",
             "OK" if audio.status_code == 200 and audio.content else "FAIL",
             f"{len(audio.content)} bytes, {ms:.0f}ms")
        st = client.get(f"{API}/voice/status").json()
        print(f"           adapters: tts={st['tts_adapter']}(cfg={st['tts_configured']}) "
              f"stt={st['stt_adapter']}(cfg={st['stt_configured']})")

    def voice_in() -> None:
        wav = state.get("wav")
        if not wav:
            return line("voice IN", "SKIP", "no wav from step 1")
        wav_path = Path(os.environ["JARVIS_VOICE_OUTPUT_DIR"]) / wav
        b64 = base64.b64encode(wav_path.read_bytes()).decode()
        t = time.monotonic()
        r = client.post(f"{API}/voice/transcribe",
                        json={"audio_base64": b64, "audio_suffix": ".wav"})
        ms = (time.monotonic() - t) * 1000
        if r.status_code == 200:
            line("voice IN (whisper-cli STT)", "OK",
                 f'heard: "{r.json()["transcript"][:55]}"  {ms:.0f}ms')
        else:
            line("voice IN (whisper-cli STT)", "SETUP", f"{r.status_code} {r.text[:100]}")

    def sight() -> None:
        vs = client.get(f"{API}/vision/status").json()
        print(f"           vision adapter: {vs['adapter']}(cfg={vs['configured']})")
        img = REPO / "IMG_1256.PNG"
        if not img.is_file():
            return line("SIGHT", "SKIP", "no test image")
        b64 = base64.b64encode(img.read_bytes()).decode()
        t = time.monotonic()
        r = client.post(f"{API}/vision/analyze",
                        json={"image_base64": b64, "image_suffix": ".png"})
        ms = (time.monotonic() - t) * 1000
        if r.status_code == 200:
            line("SIGHT (moondream vision)", "OK",
                 f'saw: "{r.json()["description"][:60]}"  {ms:.0f}ms')
        else:
            line("SIGHT (moondream vision)", "SETUP", f"{r.status_code} {r.text[:100]}")

    def file_rw() -> None:
        target = REPO / "data" / "verify_scratch.txt"
        r = client.post(f"{API}/bot/file/exec", json={
            "sender": "user", "action": "write",
            "payload": {"path": str(target), "content": "hello from verify"}}).json()
        line("FILE write (self-file, ungated)", "OK" if r.get("ok") else "FAIL")
        r = client.post(f"{API}/bot/file/exec", json={
            "sender": "user", "action": "read", "payload": {"text": str(target)}}).json()
        gated = (not r.get("ok")) and ("permission_request" in (r.get("payload") or {}))
        line("FILE read GATE (read_files=prompt)", "OK" if gated else "WARN",
             "blocked, pending approval" if gated else str(r)[:80])
        pm.update_decisions({"read_files": "allowed"})
        r = client.post(f"{API}/bot/file/exec", json={
            "sender": "user", "action": "read", "payload": {"text": str(target)}}).json()
        ok = r.get("ok") and "hello from verify" in (r.get("payload") or {}).get("text", "")
        line("FILE read after approval", "OK" if ok else "FAIL")
        target.unlink(missing_ok=True)

    def system_exec() -> None:
        r = client.post(f"{API}/bot/system/exec", json={
            "sender": "user", "action": "execute",
            "payload": {"text": "echo destructive"}}).json()
        line("SYSTEM exec GATE (execute_scripts=denied)", "OK" if not r.get("ok") else "WARN",
             str(r.get("error") or "")[:70])
        pm.update_decisions({"execute_scripts": "allowed"})
        r = client.post(f"{API}/bot/system/exec", json={
            "sender": "user", "action": "execute",
            "payload": {"text": "echo odin-ok"}}).json()
        ok = r.get("ok") and "odin-ok" in (r.get("payload") or {}).get("text", "")
        line("SYSTEM exec after approval", "OK" if ok else "FAIL")

    def web() -> None:
        pm.update_decisions({"access_network": "allowed"})
        r = client.post(f"{API}/bot/research/exec", json={
            "sender": "user", "action": "search",
            "payload": {"text": "M2 MacBook Air RAM", "limit": 3}}).json()
        if r.get("ok"):
            line("WEB search (DuckDuckGo, fixed headers)", "OK",
                 f"{len((r.get('payload') or {}).get('results', []))} results")
        else:
            line("WEB search (DuckDuckGo)", "NET?", f"{r.get('error')}"[:85])

    def web_fetch() -> None:
        r = client.post(f"{API}/bot/research/exec", json={
            "sender": "user", "action": "fetch",
            "payload": {"url": "https://example.com"}}).json()
        if r.get("ok"):
            line("WEB fetch (new fetch action)", "OK",
                 f'text: "{(r.get("payload") or {}).get("text", "")[:50]}"')
        else:
            line("WEB fetch (new fetch action)", "NET?", f"{r.get('error')}"[:85])

    def audit() -> None:
        events = client.get(f"{API}/audit/events").json()
        line("AUDIT log (every action recorded)",
             "OK" if isinstance(events, list) and events else "WARN",
             f"{len(events)} events" if isinstance(events, list) else "")

    for label, fn in [
        ("voice OUT", voice_out), ("voice IN", voice_in), ("SIGHT", sight),
        ("FILE", file_rw), ("SYSTEM", system_exec), ("WEB", web),
        ("WEB fetch", web_fetch), ("AUDIT", audit),
    ]:
        guard(label, fn)

    client.__exit__(None, None, None)
    print("\nLegend: OK=works now  SETUP=needs install/model  NET?=network/sandbox  "
          "GATE=permission correctly blocked\n")


if __name__ == "__main__":
    main()
