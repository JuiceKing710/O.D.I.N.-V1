from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse


class ResearchBot(Bot):
    name = "research"
    description = "Coordinates external lookup requests behind network permissions."

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action != "search":
            return BotResponse(ok=False, error=f"Unsupported research action: {request.action}")
        query = str(request.payload.get("text", "")).strip()
        if not query:
            return BotResponse(ok=False, error="Search query is required")
        try:
            self.permission_manager.require_allowed(
                "access_network",
                actor=request.sender,
                reason=f"Research search: {query}",
            )
        except PermissionError as exc:
            return self.permission_response(exc)
        try:
            limit = min(max(int(request.payload.get("limit", 5)), 1), 10)
        except (TypeError, ValueError):
            return BotResponse(ok=False, error="Research result limit must be an integer")
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        request_headers = {"User-Agent": "Jarvis-V1/0.1 local research assistant"}
        try:
            network_request = urllib.request.Request(url, headers=request_headers, method="GET")
            with urllib.request.urlopen(network_request, timeout=15) as response:
                body = response.read().decode("utf-8", errors="replace")
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

    def capabilities(self) -> list[str]:
        return ["search"]
