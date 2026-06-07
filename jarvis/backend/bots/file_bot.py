from __future__ import annotations

from pathlib import Path

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse


class FileBot(Bot):
    name = "file"
    description = "Handles constrained file inspection tasks."

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
                )
                path = Path(raw_path).expanduser()
                if not path.is_file():
                    return BotResponse(ok=False, error="File does not exist")
                return BotResponse(ok=True, payload={"text": path.read_text(encoding="utf-8")[:8000]})
            except PermissionError as exc:
                return self.permission_response(exc)
            except (OSError, UnicodeDecodeError) as exc:
                return BotResponse(ok=False, error=str(exc))
        return BotResponse(ok=False, error=f"Unsupported file action: {request.action}")

    def capabilities(self) -> list[str]:
        return ["read"]
