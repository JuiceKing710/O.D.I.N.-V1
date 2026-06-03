# Jarvis V1.1

Jarvis V1.1 is a local-first assistant scaffold based on the master architecture specification.
The repository is split into a FastAPI backend, a React/Electron frontend shell, scripts, and tests.

## Current Scope

This initial build includes:

- Backend API contracts for chat, memory, bots, tasks, settings, and models.
- Core orchestration with persistent SQLite-backed conversations and messages.
- Bot registry and protocol primitives.
- Permission manifest loading and audit logging.
- Voice manager and reflection engine skeletons.
- Frontend application shell with AI core, chat, dashboard, and settings components.
- Electron desktop wrapper around the built React app.
- Unit and API tests for core message handling, persistence, bot dispatch, permissions, CORS, tasks, and settings.

Heavy runtime integrations such as Whisper, Piper/Kokoro, ChromaDB, and LM Studio are represented by adapters and interfaces so they can be implemented safely behind stable contracts.

## Backend

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn jarvis.backend.api.main:app --reload
```

The backend defaults to a SQLite database at `data/jarvis.db`. Override it with:

```bash
export JARVIS_DB_PATH=/path/to/jarvis.db
```

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

Build and launch the Electron shell with:

```bash
npm run desktop
```

## Tests

```bash
python -m unittest discover -s tests
ruff check .
cd frontend && npm run build && npm audit --audit-level=moderate
```
