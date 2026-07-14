# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

O.D.I.N. (Jarvis V1.1) is a local-first personal assistant: a FastAPI backend (`jarvis/`) plus a
React/Electron frontend (`frontend/`). Ollama is the default local LLM provider; ChromaDB and
command-based TTS/STT are optional. See [README.md](README.md) for the full list of environment
variables and runtime behavior (voice, vision, memory consolidation, backups, wake word, etc.) —
it is kept current and is the source of truth for user-facing configuration, so check it before
assuming a feature doesn't exist.

## Commands

Backend setup and run:
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
uvicorn jarvis.backend.api.main:app --reload
```

Backend tests and lint:
```bash
python -m unittest discover -s tests   # run all backend tests
python -m unittest tests.test_core     # run a single test module
python -m unittest tests.test_core.TestClassName.test_method_name  # single test
ruff check .
```

Frontend:
```bash
cd frontend
npm install
npm run dev       # vite dev server against http://127.0.0.1:8000 (override with VITE_API_BASE_URL)
npm test          # vitest run
npm run build
npm run desktop   # build + launch Electron wrapper (auto-manages the backend process)
```

CI (`.github/workflows/ci.yml`) runs, in order: `ruff check .`, `python -m unittest discover -s
tests`, then in `frontend/`: `npm ci`, `npm test`, `npm run build`, `npm audit --audit-level=moderate`.
Match this sequence locally before pushing.

## Backend architecture

`jarvis/backend/core/app_factory.py` is the composition root: it constructs every manager/adapter
and wires them together (settings → provider selection → managers → `JarvisCore`), then hands the
assembled graph to `jarvis/backend/api/main.py`/`routes.py`. When adding a new subsystem, wire it
here rather than having modules reach for globals.

Core request flow: `routes.py` → `JarvisCore.handle_message` (`core/jarvis_core.py`) which:
1. persists the user message via `MemoryManager`,
2. checks for a fact-update utterance or an explicit bot command (`/bot action text` or natural
   language like `research X`, `analyze code path`, `read file X`, `run command X`),
3. otherwise builds context from identity + core memory blocks + long-term facts + vector recall,
   then streams a reply from the configured `LMProviderInterface` (optionally through the
   truthfulness/verification pass — see `design/SPEC-truthfulness-and-image-generation.md`),
4. persists the assistant reply and publishes both messages on the `EventBus`.

Key subsystems under `jarvis/backend/core/`:
- **`bot_manager.py`** dispatches to bots in `jarvis/backend/bots/` (code, research, system, file,
  desktop, image), each gated by `utils/permissions.py` (`config/permissions.json` manifest;
  `allowed`/`prompt` permission states, one-time approvals, audit logged via
  `utils/audit_logging.py`).
- **`lm_provider.py`** — Ollama-backed chat provider plus `EchoLMProvider` (tests), the
  OpenAI-compatible cloud providers `OpenRouterProvider`/`NvidiaProvider` (base
  `OpenAICompatibleProvider`), and `TurboSwitchProvider`, which routes each turn by the
  `active_model` setting: `openrouter:`/`nvidia:` scheme → that cloud provider (with local
  fallback), a bare id → that local Ollama model (overrides Gemini turbo), empty → legacy
  Gemini-turbo-or-local. New cloud providers are added via its `_CLOUD_PROVIDERS` registry.
  `jarvis_core` injects a `[Current model]` context note so Odin knows which backend is answering.
- **`memory_manager.py`** / **`vector_store.py`** — SQLite conversation/message store, core memory
  blocks (persona + user profile), long-term fact storage, and semantic recall via Ollama
  embeddings (SQLite-backed by default, Chroma optional).
- **`memory_consolidator.py`** — daily sleep-time job that distills conversations into durable
  facts/profile updates.
- **`voice_manager.py`** / **`wake_word.py`** — STT/TTS adapters (Whisper via Metal, Piper/macOS
  `say`) and openwakeword listener.
- **`vision_manager.py`** / **`image_manager.py`** — camera/screen understanding and image
  generation adapters, both Ollama-first with command/Gemini fallbacks.
- **`agent_manager.py`** — `DeepResearchAgent`, the fire-and-poll long-running research agent.
- **`heartbeat.py`**, **`safety_switch.py`**, **`identity_manager.py`**, **`improvement_manager.py`**
  — the four always-on pillars (heartbeat, safety, identity, adaptive improvement).
- **`backup_scheduler.py`** / **`recovery_manager.py`** — encrypted (AES-GCM) daily backups with
  retention and restore, coordinated with live DB activity.
- **`system_monitor.py`** — CPU/memory/disk/network telemetry streamed as `system.metrics` over the
  events WebSocket.
- **`event_bus.py`** — thread-safe pub/sub backing the WebSocket event stream; bots that cause side
  effects are not retried on failure (deliberate — see git history on async/hardening work).

`api/models.py` holds the Pydantic request/response contracts; `api/routes.py` is the (large)
single router file — group new endpoints near their existing subsystem's routes rather than
splitting further.

## Frontend architecture

Single-page React app (`frontend/src/App.jsx`) themed as a "tree of life": `OdinStage.jsx` renders
the animated Odin head/aura (reacts to live speech amplitude) with software-layer nodes above and
hardware-layer nodes below, driven by `state/systemStore.js` (telemetry) and `state/appContext.jsx`
(global state). `ipc/apiClient.js` is the sole HTTP/WebSocket boundary to the backend. Electron
(`frontend/electron/`) wraps the built app and starts/stops the FastAPI backend itself, surfacing
startup health for model/voice/memory/backups (`StartupHealth.jsx`).

Co-located `*.test.jsx`/`*.test.js` files use Vitest (`testSetup.js`); there is no separate test
directory for frontend code.

## Conventions

- Ruff enforces `line-length = 100`, target `py311` (see `[tool.ruff]` in `pyproject.toml`).
- Favor dependency injection through `app_factory.py` over module-level singletons, matching the
  existing manager/adapter pattern (interface + concrete adapters, e.g. `VectorStoreInterface`,
  `LMProviderInterface`, vision/voice/image adapters).
- Anything that can fail (missing local model, missing binary, disabled optional dependency) has an
  `Unconfigured*`/no-op adapter fallback instead of raising — keep new integrations consistent with
  this pattern.
