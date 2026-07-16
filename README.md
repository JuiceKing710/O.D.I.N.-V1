# O.D.I.N. — Optical Detection & Intelligence Network (Jarvis V1.1)

O.D.I.N. is a local-first personal assistant based on the master architecture specification.
The repository is split into a FastAPI backend, a React/Electron frontend shell, scripts, and tests.
The interface is themed after the tree-of-life mockups in `design/`: an animated Odin head at the
center, software-layer nodes above, hardware-layer nodes below, all driven by live telemetry. Odin's
eyes and aura react to real speech amplitude while the assistant talks.

## Current Scope

The current build includes:

- Backend API contracts for chat, memory, bots, tasks, settings, and models.
- Core orchestration with persistent SQLite-backed conversations and messages.
- Functional research, code analysis, system command, and file read/write bots.
- Interactive one-time permission approvals and audit logging.
- Voice transcription/synthesis adapters, reflection summaries, and vector-memory integration.
- Encrypted full-state backup, restore, daily scheduling, catch-up, and retention controls.
- Real-time system telemetry (CPU, memory, disk, network, battery, uptime) streamed over the
  events WebSocket as `system.metrics`, plus a `/api/v1/system/overview` endpoint with live
  subsystem node statuses.
- Frontend O.D.I.N. shell: tree-of-life overview stage, top status strip, live metrics rail,
  activity stream, chat, workflows, data map, and configuration panels.
- Electron desktop wrapper around the built React app.
- Unit and API tests for core message handling, persistence, bot dispatch, permissions, CORS, tasks, and settings.

Ollama is the default local LLM provider. ChromaDB and command-based TTS can be enabled through
environment configuration. Jarvis automatically uses local `whisper-cli` and the configured
Whisper model for speech input when available.

## Backend

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn jarvis.backend.api.main:app --reload
```

Jarvis expects Ollama at `http://127.0.0.1:11434` by default. In a separate terminal, start Ollama and install at least one model:

```bash
ollama serve
ollama pull llama3.2
```

Override Ollama settings with:

```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=llama3.2
export OLLAMA_TIMEOUT_SECONDS=120
```

When `OLLAMA_MODEL` is not set, Jarvis uses the model last loaded from Settings → Model
(persisted in `data/settings.json`), and otherwise auto-selects the first installed chat
model, skipping embedding-only models such as `nomic-embed-text`.

### Model providers (local + cloud)

Odin runs on interchangeable model backends, all selectable from **Settings → Model** with a
single active-model dropdown (persisted as `active_model` in `data/settings.json`):

- **Local (Ollama)** — the default, fully on-device. A bare model id (e.g. `llama3.2:3b`) is local.
- **Google Gemini (turbo mode)** — enable Turbo Mode and add a Gemini API key. Used when no other
  model is explicitly selected.
- **OpenRouter** — add one key (Settings → OpenRouter) to unlock hundreds of cloud models (Claude,
  GPT, Llama, DeepSeek…). Selected models are stored as `openrouter:<model-id>`.
- **NVIDIA** — add a key from [build.nvidia.com](https://build.nvidia.com) (Settings → NVIDIA) to
  run NVIDIA's hosted models (Nemotron and more). Stored as `nvidia:<model-id>`. When the live model
  catalog is unreachable, a small set of flagship NVIDIA models is offered as a fallback.

Cloud providers automatically fall back to the local model if unreachable, so offline use keeps
working. An explicitly selected local model overrides Turbo. Override base URLs with
`OPENROUTER_BASE_URL` and `NVIDIA_BASE_URL`. API keys are stored locally and never returned by the
API (only `*_api_key_set` booleans are exposed). Odin is told which model is currently answering, so
you can ask it what it's running on.

### Agent Skills

Odin can use **Agent Skills** — portable `SKILL.md` instruction sets it auto-matches to a request
and follows. Skills live in the `skills/` directory (override with `JARVIS_SKILLS_DIR`); each is a
folder with a `SKILL.md` (YAML frontmatter `name`/`description` + markdown body). See
[`skills/README.md`](skills/README.md). Toggle auto-matching under **Settings → Skills**
(`skills_enabled`); `/skills` in chat lists installed skills. Install more from the Agent Skills
registry, e.g. NVIDIA's verified skills:

```bash
npx skills add nvidia/skills
```

Note that most NVIDIA skills drive CUDA/Linux GPU tooling that can't run on Apple silicon — the ones
that use NVIDIA's **hosted** APIs are the ones that work here. Skill text is user-installed reference
material injected into context; any command/file/network action a skill describes still goes through
Odin's permission-gated bots.

Semantic long-term memory is on by default: every message and memory document is embedded
through Ollama's `nomic-embed-text` model into `data/vectors.db` and recalled by meaning across
conversations. Core memory blocks (Odin's persona and a profile of you) are always included in
the prompt and editable under Data Map → Core Memory. A sleep-time consolidation job runs daily
at 4:30 AM (and on demand via `POST /api/v1/memory/consolidate`), distilling recent conversations
into durable facts and refreshing the profile. Configure with `JARVIS_EMBED_MODEL`,
`JARVIS_VECTOR_DB_PATH`, `JARVIS_VECTOR_PROVIDER=disabled`, `JARVIS_CONSOLIDATION_HOUR`, or
`JARVIS_CONSOLIDATION=disabled`.

ChromaDB remains available as an alternative vector backend:

```bash
pip install -e ".[vector]"
export JARVIS_CHROMA_PATH=data/chroma
```

Enable command-based speech-to-text and text-to-speech adapters with commands that write their
transcript to stdout or create the requested output file:

```bash
export JARVIS_WHISPER_COMMAND='whisper-cli {audio_path}'
export JARVIS_TTS_COMMAND='tts-cli --text {text} --output {output_path}'
```

Odin speaks with a local Piper neural voice when `pip install -e ".[voice]"` is installed and a
voice model exists at `~/jarvis-models/piper/en_US-ryan-medium.onnx` (override with
`JARVIS_PIPER_VOICE`); otherwise speech falls back to macOS `say`. `start-odin.sh` points
`JARVIS_PIPER_VOICE` at the deep British male voice `en_GB-alan-medium.onnx` on Valhalla — download
a voice's `.onnx` *and* `.onnx.json` from [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)
to swap it. An optional wake word
(Settings → Voice; default model `hey_jarvis`, override with `JARVIS_WAKE_MODEL` once a custom
"Hey Odin" model is trained) listens through openwakeword and opens the chat dock when heard —
macOS will request microphone access for the backend on first use.

Jarvis defaults to `~/jarvis-models/ggml-base.en.bin` for local Whisper input. Override it with
`JARVIS_WHISPER_MODEL`, or use Settings → Voice → Set up local speech model to download a
compatible model. The Electron app requests macOS microphone access on first use.

Whisper runs on the Metal GPU by default (about 2× faster than CPU on Apple Silicon and it
frees the CPU cores); set `JARVIS_WHISPER_GPU=disabled` to force CPU. Every valid `ggml-*.bin`
model in `~/jarvis-models` (override the dir with `JARVIS_WHISPER_MODEL_DIR`) appears in the
Settings → Voice speech-model picker and can be switched live — the choice persists in
`data/settings.json`. Measured on an M2 Air with an 8.7 s command clip: `base.en` ≈ 1.1 s,
`large-v3-turbo-q5_0` ≈ 2.6 s warm. base.en stays the default because voice commands are
latency-sensitive; pick turbo for dictation accuracy. A wake-word-triggered streaming capture
mode was evaluated and deliberately not built: the measured round trip is already ~2–3 s and an
always-resident streaming process would hold RAM the models need.

Camera and screen vision run through local Ollama models. The default auto-selection targets the
sweet spot for the always-on security monitor — smart enough for daily use, light enough to run
continuously — preferring `qwen2.5vl:7b` (best all-round, ~6 GB, wants 16 GB RAM), then
`qwen2.5vl:3b` (~3 GB, great on 8 GB), then `minicpm-v`, then `moondream` (~1.7 GB, tiny/fast
fallback), then `llava`. Only installed models are considered, so the order just decides among what
you have already pulled — install one with e.g. `ollama pull qwen2.5vl:7b` (or `:3b` on a smaller
Mac), or pin any model with `JARVIS_VISION_MODEL`. The vision model is evicted from RAM
immediately after each analysis (`JARVIS_VISION_KEEP_ALIVE`, default `0`) so the chat model
keeps the memory, and thinking mode is disabled per frame for latency. The Chat view's
**Screen** button captures the display (`POST /api/v1/vision/screen`) and describes it — gated
behind the `observe_screen` permission (one-time approval in Settings), audit logged, and
requiring macOS Screen Recording access for the backend process in System Settings →
Privacy & Security on first use.

Jarvis recognizes explicit natural-language actions such as `research local assistants`,
`analyze code path/to/file.py`, `read file notes.txt`, and `run command date`. Slash commands
remain available as `/<bot> <action> [text]`. Permissions set to `prompt` create a pending
one-time approval in Settings. Approving it executes that exact queued action; permissions set to
`allowed` run without prompting:

```text
/code analyze path/to/file.py
/research search local-first assistants
/system execute date
```

Jarvis can write files inside its own repository without prompting. Writes outside the repository
require one-time `write_files` approval. For chat writes, put the path on the first line and the
new file content on the following lines:

```text
/file write notes/example.txt
new file content
```

The research bot performs a bounded DuckDuckGo HTML lookup, the code bot analyzes real local files,
and the system bot executes a parsed command without shell expansion.

Odin can generate images on request — natural-language phrasings such as `draw a picture of a fox
in the snow` (or `/image generate a fox in the snow`) dispatch the image bot behind the
`generate_images` permission (plus `access_network` when a cloud generator is configured). The
generated image is displayed inline in the chat, right below Odin's reply, with a **Save image**
button to keep a copy. The image reference is stored on the assistant message, so it renders again
whenever the conversation is reopened rather than disappearing after the first response. Generated
files are held in a rolling on-disk cache and served from `/api/v1/image/file/<name>`.

The backend defaults to a SQLite database at `data/jarvis.db`. Override it with:

```bash
export JARVIS_DB_PATH=/path/to/jarvis.db
```

Encrypted backups include SQLite, settings, audit logs, and configured Chroma data. Jarvis creates
a protected local key at `data/backup.key` automatically. Set an external secret to override it:

```bash
export JARVIS_BACKUP_KEY='use-a-long-random-secret'
export JARVIS_BACKUP_DIR=data/backups
```

The key is never included in a backup. Backups use AES-GCM authenticated encryption. Restore
validates the encrypted bundle and SQLite
integrity, coordinates with live database activity, then creates an encrypted safety backup of the
current database before replacement.
While the backend is running, it creates a backup every day at 4:00 AM local time and retains the
latest 30 backups. Override this with `JARVIS_BACKUP_HOUR`, `JARVIS_BACKUP_RETENTION`, or disable it
with `JARVIS_SCHEDULED_BACKUPS=disabled`. If Jarvis starts after 4:00 AM without a backup from that
day, it creates a catch-up backup immediately.

Local frontend origins are allowed by default for development and preview. Override them with:

```bash
export JARVIS_ALLOWED_ORIGINS=http://127.0.0.1:4173,http://127.0.0.1:5173
```

### Remote access from your phone

Odin can be reached from your phone while you're away from home. The whole web UI is served by the
backend itself, so the phone loads it same-origin and talks to Odin the same way the desktop does —
no separate app to install. Because that exposes an API that can run commands, read files, and see
the camera/screen, remote access is **off by default** and gated behind a shared token. Never
port-forward the raw backend to the public internet; use a private network (Tailscale) instead.

**One-time setup**

1. Install [Tailscale](https://tailscale.com/) on the Mac running Odin and on your phone, and sign
   both into the same tailnet. This gives them a private encrypted link with no ports opened to the
   internet.
2. Turn on remote auth and pick a token (or let one be generated at `data/api.key` — with the
   Valhalla launcher, `$ODIN_DATA/api.key`):

   ```bash
   export JARVIS_REQUIRE_AUTH=1
   export JARVIS_API_TOKEN="$(openssl rand -base64 32)"   # optional; omit to auto-generate
   ```

3. Build the web UI so the backend can serve it (rebuild after frontend changes):

   ```bash
   cd frontend && npm run build
   ```

4. Start the backend listening on all interfaces so Tailscale can reach it:

   ```bash
   ./start-odin.sh backend --host 0.0.0.0 --port 8000
   ```

5. Publish it over HTTPS on your tailnet with a real certificate:

   ```bash
   tailscale serve https / http://127.0.0.1:8000
   ```

   HTTPS matters: browsers only allow microphone/voice input on a secure origin, so text chat works
   over plain `http://<machine>:8000` within the tailnet but **voice needs the `tailscale serve`
   HTTPS address**. `tailscale serve status` prints the `https://<machine>.<tailnet>.ts.net` URL.

**Connecting the phone**

With Tailscale active on the phone, open the `https://<machine>.<tailnet>.ts.net` address in the
phone's browser. The first request prompts for the access token; copy it from the Mac under
**Settings → Remote Access** (Configuration panel) and paste it in once. It is stored on that device
so you won't be asked again until you clear it. Keep the token private — it grants full access to
Odin, and anyone with it can act as you.

Auth is enforced by a token middleware (`JARVIS_REQUIRE_AUTH`, `JARVIS_API_TOKEN`,
`JARVIS_API_TOKEN_PATH`) that gates everything under `/api/` with a constant-time comparison; the
served UI and the `/healthz` liveness probe stay open so the phone can load the page and present the
token. The token may be supplied as an `Authorization: Bearer` header, an `X-Odin-Token` header, or a
`?token=` query parameter (the WebSocket event stream uses the query form, since browsers can't set
headers on a WebSocket). With auth off, the middleware is a no-op and local use is unchanged.

[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
works as an alternative to Tailscale if you want a public hostname instead of a private tailnet —
keep `JARVIS_REQUIRE_AUTH=1` on either way.

### Security camera monitor

Odin can watch a security camera / NVR system and alert you when it sees something — a person,
motion, a package, a vehicle — using the same local vision model, so **frames never leave the
machine**. A background loop grabs one still frame per camera on an interval, asks the vision model
whether any watched event is present, and on a hit publishes a live `security.alert` and fires a
phone push notification. A per-camera cooldown keeps a lingering person from re-alerting every
cycle. It is **off by default**.

The app has a dedicated **Security** tab: monitor and per-camera health, the current watch list,
a **Scan now** button to check every camera on demand, and a live gallery of recent alerts with the
snapshot that triggered each one. Alerts also appear in the Overview activity feed as they happen.

This works with any NVR/IP camera that exposes an **RTSP** stream — ZOSI, Reolink, Amcrest,
Hikvision, Dahua, and generic ONVIF systems. Most 8-channel NVRs expose one RTSP URL per channel
behind a single IP.

**1. Put the NVR on your network and enable RTSP.** Connect the NVR to your router by Ethernet
(this keeps footage on your LAN — it is *not* exposing cameras to the internet), give it a static IP
or a DHCP reservation, and enable RTSP/ONVIF in the NVR's network settings. Note the RTSP port
(usually 554) and the stream path — for ZOSI it's typically
`rtsp://<user>:<password>@<nvr-ip>:554/ch0<N>/0` for channel *N* (main stream) or `.../ch0<N>/1`
for the lighter sub-stream. Confirm a URL works with `ffplay "<rtsp-url>"` before wiring it in.

**2. Install ffmpeg** (used to grab one frame without holding the stream open):

```bash
brew install ffmpeg
```

**3. List your cameras** in a JSON file (default `data/cameras.json`, override with
`JARVIS_CAMERA_CONFIG`). Use the sub-stream to keep it light; `transport` defaults to `tcp`:

```json
[
  { "name": "Front Door", "url": "rtsp://admin:PASSWORD@192.168.1.50:554/ch01/1" },
  { "name": "Driveway",   "url": "rtsp://admin:PASSWORD@192.168.1.50:554/ch02/1" }
]
```

**4. Set up phone push (optional but recommended for when you're away).** Install the free
[ntfy](https://ntfy.sh/) app on your phone and subscribe to an unguessable topic; give Odin the same
topic. Anyone who knows the topic can read the alerts, so treat it like the access token. A
self-hosted ntfy server works too via `JARVIS_NTFY_URL`/`JARVIS_NTFY_TOKEN`. Without this, alerts
still appear live in the Odin app.

**5. Turn the monitor on** and start the backend:

```bash
export JARVIS_SECURITY_MONITOR=enabled
export JARVIS_NTFY_TOPIC=odin-a7f3k9-alerts      # optional: phone push
./start-odin.sh backend --host 0.0.0.0 --port 8000
```

Tuning env vars: `JARVIS_SECURITY_INTERVAL_SECONDS` (scan cadence, default 30),
`JARVIS_SECURITY_COOLDOWN_SECONDS` (per-camera quiet window after an alert, default 180),
`JARVIS_SECURITY_WATCH` (`;`-separated list of things to flag; defaults to people/motion/packages/
vehicles), `JARVIS_SECURITY_CAPTURE_DIR` (where triggering frames are saved, default `data/security`),
`JARVIS_SECURITY_MAX_CAPTURES` (rolling cap, default 100), and `JARVIS_SECURITY_GRAB_TIMEOUT_SECONDS`
(per-frame ffmpeg timeout, default 20). A local vision model must be installed (see the vision
section) for detection to run.

Endpoints: `GET /api/v1/security/status` (monitor + per-camera health), `GET /api/v1/security/alerts`
(recent alerts), `POST /api/v1/security/scan` (check every camera now — useful to validate setup),
and `GET /api/v1/security/capture/{name}` (a saved snapshot). Because these live under `/api/`, the
remote-access token gates them too, so you can check your cameras from your phone over Tailscale.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the backend at `http://127.0.0.1:8000` unless `VITE_API_BASE_URL` is set.

Build and launch the Electron app with:

```bash
npm run desktop
```

The desktop app starts and stops the FastAPI backend automatically and reports startup health for
the model, voice, memory, and backups. Use the Data panel to export/delete conversations, remove
long-term memory documents, and inspect the audit log.

## Tests

```bash
python -m unittest discover -s tests
ruff check .
cd frontend && npm run build && npm audit --audit-level=moderate
cd frontend && npm test
```
