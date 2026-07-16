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

Camera and screen vision run through local Ollama models. Auto-selection prefers
`qwen3.5:0.8b` (fastest verified small VLM, ~2 s per frame warm), then `qwen3.5:2b`, then
`moondream`/`llava`; override with `JARVIS_VISION_MODEL`. The vision model is evicted from RAM
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
