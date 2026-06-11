# Jarvis V1.1

Jarvis V1.1 is a local-first personal assistant based on the master architecture specification.
The repository is split into a FastAPI backend, a React/Electron frontend shell, scripts, and tests.

## Current Scope

The current build includes:

- Backend API contracts for chat, memory, bots, tasks, settings, and models.
- Core orchestration with persistent SQLite-backed conversations and messages.
- Functional research, code analysis, system command, and file read/write bots.
- Interactive one-time permission approvals and audit logging.
- Voice transcription/synthesis adapters, reflection summaries, and vector-memory integration.
- Encrypted full-state backup, restore, daily scheduling, catch-up, and retention controls.
- Frontend application shell with AI core, chat, dashboard, and settings components.
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

Jarvis defaults to `~/jarvis-models/ggml-base.en.bin` for local Whisper input. Override it with
`JARVIS_WHISPER_MODEL`, or use Settings → Voice → Set up local speech model to download a
compatible model. The Electron app requests macOS microphone access on first use.

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
