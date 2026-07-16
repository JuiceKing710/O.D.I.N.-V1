# Launching O.D.I.N. (Valhalla setup)

All of Odin's data — conversations, memories, settings, backups, voice files —
lives on the **Valhalla** flash drive at `/Volumes/Valhalla/odin/data/`.
The code stays here in this repo. `start-odin.sh` connects the two and refuses
to start if the drive isn't plugged in (so Odin can never boot with an empty
brain by accident).

## Before anything

Plug in Valhalla and wait for it to appear in Finder.

## Launch

```bash
cd "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/O.D.I.N.-V1"

./start-odin.sh desktop        # full app (Electron UI + backend)
./start-odin.sh                # backend only, http://127.0.0.1:8000
./start-odin.sh backend --reload   # backend with auto-reload (dev)
```

For a shell session that needs Odin's storage paths (tests, scripts, manual
uvicorn):

```bash
eval "$(./start-odin.sh env)"
```

## Rules

- **Always launch through `start-odin.sh`** — never bare `uvicorn` or
  `npm run desktop`, and never Electron from Finder/Dock. Those get no
  `JARVIS_*` env vars and would start a fresh, empty database.
- **Eject Valhalla before unplugging** (Finder eject or
  `diskutil eject /Volumes/Valhalla`). Yanking it mid-write is the one way to
  corrupt the databases.

## If it won't start

| Message | Meaning |
|---|---|
| `✗ Valhalla is not mounted` | Plug the drive in, wait a few seconds, retry. |
| `✗ .../jarvis.db is missing` | Drive is mounted but has no Odin data — wrong drive, or the data was moved. Don't proceed; find the data first. |

The pre-migration snapshot of Odin's data (as of 2026-07-13) is kept at
`data.pre-valhalla-2026-07-13/` in this repo as a fallback.
