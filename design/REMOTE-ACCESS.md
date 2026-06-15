# Reaching Odin from your phone (Tailscale + token auth)

Goal: talk to Odin from your phone when you're away from home, **without putting
Odin on the public internet.** Odin can read/write files and run system commands,
so the design keeps it on a private encrypted network (Tailscale) and adds an app
token on top.

## How it fits together

```
Phone browser ──(Tailscale, encrypted)──► Mac:  tailscale serve (HTTPS)
                                                 └─► 127.0.0.1:8000  (Odin backend)
Every /api request must carry the access token. The web UI is served by the
backend itself, so it loads over the same HTTPS origin (no CORS, and HTTPS is
what lets the phone use the camera/mic).
```

Two layers of protection:
1. **Tailscale** — only your own devices can even reach the Mac. No port
   forwarding, works behind your ISP's NAT.
2. **App token** — every API call needs a secret token, so a stray device on the
   tailnet still can't drive Odin.

## One-time setup

### 1. Build the web UI (so the backend can serve it to the phone)
```
cd frontend && npm run build      # produces frontend/dist
```
The backend auto-serves `frontend/dist` at `/` when it exists (override with
`JARVIS_STATIC_DIR`).

### 2. Choose an access token
Pick a strong token and start the backend with auth on:
```
JARVIS_REQUIRE_AUTH=1 JARVIS_API_TOKEN='<a-long-random-string>' \
  .venv/bin/python -m uvicorn jarvis.backend.api.main:app --host 127.0.0.1 --port 8000
```
- If you omit `JARVIS_API_TOKEN`, Odin generates one and stores it in
  `data/api.key` (also printed nowhere sensitive — read it from that file).
- Setting it explicitly is recommended: the desktop app picks it up from the
  environment automatically, and it shows in **Configuration → Remote Access**
  with a Copy button.

> Default (no `JARVIS_REQUIRE_AUTH`) = auth off, local-only — exactly as before.

### 3. Install Tailscale (you do this — it needs your account)
- Install Tailscale on the **Mac** and on your **phone**, sign in to the **same**
  account on both. (Account creation/sign-in is yours to do — I can't log in for you.)
- On the Mac, expose the backend over HTTPS on your tailnet:
  ```
  tailscale serve --bg 8000
  ```
  Tailscale prints an HTTPS URL like `https://<your-mac>.<tailnet>.ts.net`.

### 4. Connect from the phone
- With Tailscale active on the phone, open that HTTPS URL in the phone browser.
- The web UI loads; when it asks, paste the access token (copy it from the Mac's
  **Configuration → Remote Access**). It's stored on the phone for next time.
- Optional: "Add to Home Screen" to use it like an app (PWA).

## Notes & limits
- **Camera/mic on the phone need HTTPS** — that's why we use `tailscale serve`
  (it provides a real cert), not a raw `http://<ip>:8000`.
- The token grants **full** access (per your choice). If a device is lost, rotate
  it: change `JARVIS_API_TOKEN` (or delete `data/api.key`) and restart; re-enter
  the new token on your devices.
- This does **not** open any router ports and never exposes Odin publicly.
- To turn remote access off entirely, stop `tailscale serve` and start the
  backend without `JARVIS_REQUIRE_AUTH`.

## Env vars added for this
| Var | Meaning |
|-----|---------|
| `JARVIS_REQUIRE_AUTH` | `1`/`true` to require the token on all `/api` requests |
| `JARVIS_API_TOKEN` | the token to require (else one is generated in `data/api.key`) |
| `JARVIS_API_TOKEN_PATH` | where the generated token is stored (default `data/api.key`) |
| `JARVIS_STATIC_DIR` | override the served web-UI directory (default `frontend/dist`) |
