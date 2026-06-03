from __future__ import annotations

from pathlib import Path

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse


class FileBot(Bot):
    name = "file"
    description = "Handles constrained file inspection tasks."

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action == "read":
            try:
                self.permission_manager.require_allowed("read_files")
                path = Path(str(request.payload.get("text", ""))).expanduser()
                if not path.is_file():
                    return BotResponse(ok=False, error="File does not exist")
                return BotResponse(ok=True, payload={"text": path.read_text(encoding="utf-8")[:8000]})
            except (OSError, UnicodeDecodeError, PermissionError) as exc:
                return BotResponse(ok=False, error=str(exc))
        return BotResponse(ok=False, error=f"Unsupported file action: {request.action}")

    def capabilities(self) -> list[str]:
        return ["read"]

