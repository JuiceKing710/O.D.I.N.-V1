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

Ollama is the default local LLM provider. ChromaDB, command-based Whisper transcription,
and command-based TTS can be enabled through environment configuration.

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

Enable persistent vector memory with:

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

Bot chat commands use `/<bot> <action> [text]`. Permissions set to `prompt` create a pending
one-time approval in Settings; permissions set to `allowed` run without prompting:

```text
/code analyze path/to/file.py
/research search local-first assistants
/system execute date
```

The research bot performs a bounded DuckDuckGo HTML lookup, the code bot analyzes real local files,
and the system bot executes a parsed command without shell expansion.

The backend defaults to a SQLite database at `data/jarvis.db`. Override it with:

```bash
export JARVIS_DB_PATH=/path/to/jarvis.db
```

Encrypted SQLite backups and restore require an external secret. The key is never written into a
backup or settings file:

```bash
export JARVIS_BACKUP_KEY='use-a-long-random-secret'
export JARVIS_BACKUP_DIR=data/backups
```

Backups use AES-GCM authenticated encryption. Restore validates the encrypted file and SQLite
integrity, then creates an encrypted safety backup of the current database before replacement.

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
