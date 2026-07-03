from __future__ import annotations

import asyncio
import time

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse
from jarvis.backend.core.image_manager import ImageManager
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import PermissionManager


class ImageBot(Bot):
    name = "image"
    description = "Generates images from a text prompt behind a generate-images permission."
    # Generation is slow by nature: the Gemini adapter allows 60s and a local
    # command adapter up to 300s. The dispatch timeout must cover the slowest.
    timeout_seconds = 310.0

    # Serialize and space out generations so a cloud generator is not hammered.
    MIN_REQUEST_INTERVAL = 1.0

    def __init__(
        self,
        permission_manager: PermissionManager,
        audit_logger: AuditLogger,
        image_manager: ImageManager,
    ) -> None:
        super().__init__(permission_manager, audit_logger)
        self.image_manager = image_manager
        self._throttle_lock = asyncio.Lock()
        self._last_request = 0.0

    def capabilities(self) -> list[str]:
        return ["generate"]

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action != "generate":
            return BotResponse(ok=False, error=f"Unsupported image action: {request.action}")
        prompt = str(request.payload.get("text") or request.payload.get("prompt") or "").strip()
        if not prompt:
            return BotResponse(ok=False, error="An image prompt is required")

        # Always gate image generation on its own permission so the user is asked
        # the first time; additionally gate the network when the generator is cloud.
        try:
            self.permission_manager.require_allowed(
                "generate_images",
                actor=request.sender,
                reason=f"Generate image: {prompt}",
                metadata=self.permission_metadata(request),
            )
            if self.image_manager.status().network:
                self.permission_manager.require_allowed(
                    "access_network",
                    actor=request.sender,
                    reason=f"Cloud image generation: {prompt}",
                    metadata=self.permission_metadata(request),
                )
        except PermissionError as exc:
            return self.permission_response(exc)

        await self._throttle()
        try:
            # Adapters call urllib/subprocess synchronously; run generation off
            # the event loop so a 60-300s render doesn't freeze the process.
            path = await asyncio.to_thread(self.image_manager.generate, prompt)
        except RuntimeError as exc:
            return BotResponse(ok=False, error=str(exc))
        return BotResponse(
            ok=True,
            payload={
                "text": f"Here's an AI-generated image of: {prompt}",
                "image_url": f"/api/v1/image/file/{path.name}",
                "prompt": prompt,
            },
        )

    async def _throttle(self) -> None:
        async with self._throttle_lock:
            wait = self.MIN_REQUEST_INTERVAL - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()
