from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        actor: str,
        action: str,
        result: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "action": action,
            "result": result,
            "metadata": metadata or {},
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True))
            handle.write("\n")

