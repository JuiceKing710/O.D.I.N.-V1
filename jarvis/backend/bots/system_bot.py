from __future__ import annotations

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse


class SystemBot(Bot):
    name = "system"
    description = "Mediates local system actions behind explicit permissions."

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action != "execute":
            return BotResponse(ok=False, error=f"Unsupported system action: {request.action}")
        try:
            self.permission_manager.require_allowed("execute_scripts")
        except PermissionError as exc:
            return BotResponse(ok=False, error=str(exc))
        command = str(request.payload.get("text", "")).strip()
        if not command:
            return BotResponse(ok=False, error="Command text is required")
        return BotResponse(
            ok=True,
            payload={"text": f"Execution requires an interactive approval flow: {command}"},
        )

    def capabilities(self) -> list[str]:
        return ["execute"]

