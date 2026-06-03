from __future__ import annotations

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse


class CodeBot(Bot):
    name = "code"
    description = "Analyzes code-related requests without executing generated code."

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action != "analyze":
            return BotResponse(ok=False, error=f"Unsupported code action: {request.action}")
        text = str(request.payload.get("text", "")).strip()
        if not text:
            return BotResponse(ok=False, error="Code analysis input is required")
        return BotResponse(ok=True, payload={"text": f"Code analysis request accepted: {text[:200]}"})

    def capabilities(self) -> list[str]:
        return ["analyze"]

