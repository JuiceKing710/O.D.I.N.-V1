#!/bin/bash
# Launch O.D.I.N. with all data/storage on the Valhalla flash drive.
#
# Usage:
#   ./start-odin.sh                 # backend (uvicorn) with Valhalla storage
#   ./start-odin.sh backend --reload
#   ./start-odin.sh desktop         # Electron app (backend auto-managed)
#   eval "$(./start-odin.sh env)"   # just export the vars into this shell
set -euo pipefail

VOLUME="/Volumes/Valhalla"
ODIN_DATA="$VOLUME/odin/data"

# Hard mount check. A plain "directory exists" test is not enough: if the
# drive is unplugged and anything writes to $VOLUME, macOS creates a ghost
# folder on the internal disk — O.D.I.N. would then silently start a fresh,
# empty brain there instead of failing loudly.
if ! mount | grep -q " on $VOLUME ("; then
  echo "✗ Valhalla is not mounted. Plug in the drive, then retry." >&2
  exit 1
fi
if [ ! -f "$ODIN_DATA/jarvis.db" ]; then
  echo "✗ $ODIN_DATA/jarvis.db is missing — Valhalla is mounted but has no O.D.I.N. data." >&2
  exit 1
fi

VARS=(
  "JARVIS_DB_PATH=$ODIN_DATA/jarvis.db"
  "JARVIS_VECTOR_DB_PATH=$ODIN_DATA/vectors.db"
  "JARVIS_SETTINGS_PATH=$ODIN_DATA/settings.json"
  "JARVIS_BACKUP_DIR=$ODIN_DATA/backups"
  "JARVIS_BACKUP_KEY_PATH=$ODIN_DATA/backup.key"
  "JARVIS_AUDIT_LOG=$ODIN_DATA/audit.log"
  "JARVIS_PERMISSION_REQUESTS_PATH=$ODIN_DATA/permissions.json"
  "JARVIS_FILE_SNAPSHOT_DIR=$ODIN_DATA/file_snapshots"
  "JARVIS_IMAGE_OUTPUT_DIR=$ODIN_DATA/images"
  "JARVIS_VOICE_OUTPUT_DIR=$ODIN_DATA/voice"
  "JARVIS_PIPER_VOICE=$ODIN_DATA/piper/en_GB-alan-medium.onnx"
  "JARVIS_API_TOKEN_PATH=$ODIN_DATA/api.key"
)

MODE="${1:-backend}"

if [ "$MODE" = "env" ]; then
  for kv in "${VARS[@]}"; do echo "export $kv"; done
  exit 0
fi

for kv in "${VARS[@]}"; do export "$kv"; done

cd "$(dirname "$0")"
case "$MODE" in
  backend)
    shift || true
    exec .venv/bin/python -m uvicorn jarvis.backend.api.main:app "$@"
    ;;
  desktop)
    cd frontend
    exec npm run desktop
    ;;
  *)
    echo "Unknown mode: $MODE (use backend | desktop | env)" >&2
    exit 1
    ;;
esac
