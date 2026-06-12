from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
