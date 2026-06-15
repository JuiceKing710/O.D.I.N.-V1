from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from jarvis.backend.api.routes import router
import asyncio

from jarvis.backend.core.app_factory import (
    get_backup_scheduler,
    get_core,
    get_memory_consolidator,
    get_settings_store,
    get_system_monitor,
    get_wake_word_listener,
)
from jarvis.backend.utils.auth import TokenAuthMiddleware, resolve_api_token


DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


def _allowed_origins() -> list[str]:
    raw = os.environ.get("JARVIS_ALLOWED_ORIGINS")
    if not raw:
        return DEFAULT_ALLOWED_ORIGINS
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _static_dir() -> Path | None:
    """Built web UI to serve same-origin (so the phone loads it over HTTPS).

    JARVIS_STATIC_DIR overrides; otherwise the Vite build at frontend/dist is
    used when present. Returns None when there is no build (tests/dev), so
    serving is skipped cleanly.
    """
    configured = os.environ.get("JARVIS_STATIC_DIR")
    if configured:
        path = Path(configured)
        return path if path.is_dir() else None
    default = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return default if (default / "index.html").is_file() else None


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        get_core()
        scheduler = get_backup_scheduler()
        scheduler.start()
        monitor = get_system_monitor()
        monitor.start()
        consolidator = get_memory_consolidator()
        consolidator.start()
        wake_listener = get_wake_word_listener()
        wake_listener.bind_loop(asyncio.get_running_loop())
        if get_settings_store().read().get("wake_word"):
            wake_listener.start()
        try:
            yield
        finally:
            wake_listener.stop()
            await consolidator.stop()
            await monitor.stop()
            await scheduler.stop()

    app = FastAPI(title="Jarvis V1.1", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        # Unauthenticated liveness probe (used by the desktop launcher and any
        # tunnel health check); intentionally reveals nothing beyond "alive".
        return {"ok": True}

    # Token gate runs first (added last = outermost is CORS); CORS handles the
    # OPTIONS preflight, which the auth middleware explicitly lets through.
    app.add_middleware(TokenAuthMiddleware, token=resolve_api_token())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Odin-Token"],
    )
    app.include_router(router)
    static_dir = _static_dir()
    if static_dir is not None:
        # Mounted last so the explicit /api routes always win; this catches the
        # rest and serves the SPA (html=True falls back to index.html).
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app


app = create_app()
