from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path
from urllib.parse import parse_qs

from starlette.responses import JSONResponse


# Liveness probe and anything not under the API prefix (the served web UI and its
# assets) stay open; only the API itself is gated. The phone must load the UI
# before it can present a token.
PROTECTED_PREFIX = "/api/"
EXEMPT_PATHS = frozenset({"/healthz"})

_TRUTHY = {"1", "true", "yes", "on", "enabled"}


def auth_required() -> bool:
    """True when remote auth is switched on via JARVIS_REQUIRE_AUTH."""
    return os.environ.get("JARVIS_REQUIRE_AUTH", "").strip().lower() in _TRUTHY


def resolve_api_token() -> str | None:
    """The token to enforce, or None when auth is disabled.

    Priority: JARVIS_API_TOKEN env, else a generated/persisted key file
    (JARVIS_API_TOKEN_PATH, default data/api.key) created with 0600 perms the
    same way the backup key is. Returns None when auth is not required so the
    middleware becomes a no-op and local use is unchanged.
    """
    if not auth_required():
        return None
    configured = os.environ.get("JARVIS_API_TOKEN")
    if configured and configured.strip():
        return configured.strip()
    key_path = Path(os.environ.get("JARVIS_API_TOKEN_PATH", "data/api.key"))
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        key_path.chmod(0o600)
    return key_path.read_text(encoding="utf-8").strip()


def _present_token(scope: dict) -> str | None:
    """Pull a token from the Authorization header, X-Odin-Token, or ?token=."""
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin-1").lower()
        if name == "authorization":
            value = raw_value.decode("latin-1").strip()
            if value.lower().startswith("bearer "):
                return value[7:].strip()
        elif name == "x-odin-token":
            return raw_value.decode("latin-1").strip()
    # WebSockets can't set headers from the browser, so accept a query param too.
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    token = query.get("token", [None])[0]
    return token.strip() if token else None


class TokenAuthMiddleware:
    """Pure-ASGI middleware that gates the API behind a shared token.

    Handles both HTTP and WebSocket scopes. When ``token`` is None (auth off) it
    passes everything through unchanged. CORS preflight (OPTIONS) is allowed so
    cross-origin browsers can negotiate before sending the token.
    """

    def __init__(self, app, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if (
            self.token is None
            or scope["type"] not in ("http", "websocket")
            or scope.get("method") == "OPTIONS"
        ):
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith(PROTECTED_PREFIX) or path in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        presented = _present_token(scope)
        if presented is not None and hmac.compare_digest(presented, self.token):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            response = JSONResponse(
                {"detail": "Missing or invalid API token"}, status_code=401
            )
            await response(scope, receive, send)
