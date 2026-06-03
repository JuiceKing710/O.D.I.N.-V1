from __future__ import annotations

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse


class ResearchBot(Bot):
    name = "research"
    description = "Coordinates external lookup requests behind network permissions."

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action != "search":
            return BotResponse(ok=False, error=f"Unsupported research action: {request.action}")
        try:
            self.permission_manager.require_allowed("access_network")
        except PermissionError as exc:
            return BotResponse(ok=False, error=str(exc))
        query = str(request.payload.get("text", "")).strip()
        if not query:
            return BotResponse(ok=False, error="Search query is required")
        return BotResponse(
            ok=True,
            payload={"text": f"Research request queued for approved network lookup: {query}"},
        )

    def capabilities(self) -> list[str]:
        return ["search"]

