from __future__ import annotations

import asyncio
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse

# DuckDuckGo's HTML endpoint serves a result-less page to bare/minimal clients,
# so we present as a normal browser. Without the Accept headers the request is
# fingerprinted as a bot and returns zero results.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_FETCH_BYTES = 2_000_000
MAX_TEXT_CHARS = 8000


def _html_to_text(body: str) -> str:
    body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", body)
    body = re.sub(r"(?is)<br\s*/?>", "\n", body)
    body = re.sub(r"(?is)</(p|div|h[1-6]|li|tr)>", "\n", body)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", body))
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


class ResearchBot(Bot):
    name = "research"
    description = "Coordinates external lookup and page fetches behind network permissions."

    # Basic per-process rate limit: serialize requests and keep a minimum gap so
    # Odin does not hammer external services.
    MIN_REQUEST_INTERVAL = 1.0

    def __init__(self, permission_manager, audit_logger) -> None:
        super().__init__(permission_manager, audit_logger)
        self._throttle_lock = asyncio.Lock()
        self._last_request = 0.0

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action == "search":
            return await self._search(request)
        if request.action == "fetch":
            url = str(request.payload.get("text") or request.payload.get("url") or "").strip()
            if not url:
                return BotResponse(ok=False, error="A URL is required to fetch")
            return await self._fetch(request, url)
        return BotResponse(ok=False, error=f"Unsupported research action: {request.action}")

    def capabilities(self) -> list[str]:
        return ["search", "fetch"]

    async def _throttle(self) -> None:
        async with self._throttle_lock:
            wait = self.MIN_REQUEST_INTERVAL - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def _search(self, request: BotRequest) -> BotResponse:
        query = str(request.payload.get("text", "")).strip()
        if not query:
            return BotResponse(ok=False, error="Search query is required")
        try:
            self.permission_manager.require_allowed(
                "access_network",
                actor=request.sender,
                reason=f"Research search: {query}",
                metadata=self.permission_metadata(request),
            )
        except PermissionError as exc:
            return self.permission_response(exc)
        try:
            limit = min(max(int(request.payload.get("limit", 5)), 1), 10)
        except (TypeError, ValueError):
            return BotResponse(ok=False, error="Research result limit must be an integer")
        await self._throttle()
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        try:
            # urllib is blocking; run it off the event loop so a slow search
            # (up to 15s) doesn't stall every other request in the process.
            body = await asyncio.to_thread(self._http_get_text, url, 15)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return BotResponse(ok=False, error=f"Research lookup failed: {exc}")

        results = []
        pattern = re.compile(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for href, raw_title in pattern.findall(body):
            title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            decoded_url = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
            if title and decoded_url:
                results.append({"title": title, "url": decoded_url})
            if len(results) >= limit:
                break
        if not results:
            return BotResponse(ok=False, error="Research lookup returned no results")
        text = "\n".join(
            f"{index}. {result['title']} - {result['url']}"
            for index, result in enumerate(results, start=1)
        )
        return BotResponse(ok=True, payload={"text": text, "query": query, "results": results})

    async def _fetch(self, request: BotRequest, url: str) -> BotResponse:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return BotResponse(ok=False, error="Only http(s) URLs can be fetched")
        try:
            self.permission_manager.require_allowed(
                "access_network",
                actor=request.sender,
                reason=f"Fetch page: {url}",
                metadata=self.permission_metadata(request),
            )
        except PermissionError as exc:
            return self.permission_response(exc)
        await self._throttle()
        try:
            content_type, raw = await asyncio.to_thread(self._http_get_page, url, 20)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return BotResponse(ok=False, error=f"Page fetch failed: {exc}")
        if content_type and "html" not in content_type and not content_type.startswith("text/"):
            return BotResponse(ok=False, error=f"Unsupported content type: {content_type}")
        body = raw[:MAX_FETCH_BYTES].decode("utf-8", errors="replace")
        text = _html_to_text(body)[:MAX_TEXT_CHARS]
        if not text:
            return BotResponse(ok=False, error="Page had no readable text")
        return BotResponse(
            ok=True,
            payload={"text": text, "url": url, "content_type": content_type or "text/html"},
        )

    @staticmethod
    def _http_get_text(url: str, timeout: float) -> str:
        request = urllib.request.Request(url, headers=BROWSER_HEADERS, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    @classmethod
    def _http_get_page(cls, url: str, timeout: float) -> tuple[str, bytes]:
        request = urllib.request.Request(url, headers=BROWSER_HEADERS, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return cls._content_type(response), response.read()

    @staticmethod
    def _content_type(response) -> str:
        headers = getattr(response, "headers", None)
        if headers is None:
            return ""
        getter = getattr(headers, "get_content_type", None)
        if callable(getter):
            return getter()
        return (headers.get("Content-Type") or "").split(";")[0].strip()
