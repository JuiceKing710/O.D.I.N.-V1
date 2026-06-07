from __future__ import annotations

import os
import tempfile
from pathlib import Path

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse

MAX_WRITE_BYTES = 1_000_000


class FileBot(Bot):
    name = "file"
    description = "Handles constrained file read and write tasks."

    def __init__(self, permission_manager, audit_logger, self_root: Path | str | None = None) -> None:
        super().__init__(permission_manager, audit_logger)
        self.self_root = Path(self_root or Path.cwd()).expanduser().resolve()

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action == "read":
            raw_path = str(request.payload.get("text", "")).strip()
            if not raw_path:
                return BotResponse(ok=False, error="File path is required")
            try:
                self.permission_manager.require_allowed(
                    "read_files",
                    actor=request.sender,
                    reason=f"Read file: {raw_path}",
                    metadata=self.permission_metadata(request),
                )
                path = Path(raw_path).expanduser()
                if not path.is_file():
                    return BotResponse(ok=False, error="File does not exist")
                return BotResponse(ok=True, payload={"text": path.read_text(encoding="utf-8")[:8000]})
            except PermissionError as exc:
                return self.permission_response(exc)
            except (OSError, UnicodeDecodeError) as exc:
                return BotResponse(ok=False, error=str(exc))
        if request.action == "write":
            try:
                raw_path, content = self._write_payload(request.payload)
                path = Path(raw_path).expanduser().resolve()
                if not self._is_self_file(path):
                    self.permission_manager.require_allowed(
                        "write_files",
                        actor=request.sender,
                        reason=f"Write file: {path}",
                        metadata=self.permission_metadata(request),
                    )
                self._atomic_write(path, content)
                return BotResponse(
                    ok=True,
                    payload={
                        "text": f"Wrote {len(content.encode('utf-8'))} bytes to {path}",
                        "path": str(path),
                        "self_file": self._is_self_file(path),
                    },
                )
            except PermissionError as exc:
                return self.permission_response(exc)
            except (OSError, UnicodeEncodeError, ValueError) as exc:
                return BotResponse(ok=False, error=str(exc))
        return BotResponse(ok=False, error=f"Unsupported file action: {request.action}")

    def capabilities(self) -> list[str]:
        return ["read", "write"]

    def _is_self_file(self, path: Path) -> bool:
        return path == self.self_root or self.self_root in path.parents

    @staticmethod
    def _write_payload(payload: dict) -> tuple[str, str]:
        raw_path = str(payload.get("path") or "").strip()
        content = payload.get("content")
        if not raw_path:
            text = str(payload.get("text") or "")
            raw_path, separator, content = text.partition("\n")
            raw_path = raw_path.strip()
            if not separator:
                raise ValueError("File write format is path on the first line, then content")
        if not raw_path:
            raise ValueError("File path is required")
        if not isinstance(content, str):
            raise ValueError("File content must be text")
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ValueError("File content exceeds the 1 MB write limit")
        return raw_path, content

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        if path.exists() and not path.is_file():
            raise ValueError(f"Path is not a file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_mode = path.stat().st_mode if path.exists() else None
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
        try:
            if existing_mode is not None:
                os.chmod(temporary_path, existing_mode)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
