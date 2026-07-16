from __future__ import annotations

import urllib.error
import urllib.request
from typing import Protocol


class Notifier(Protocol):
    name: str
    configured: bool

    def notify(self, title: str, message: str, priority: str = "default") -> None:
        """Deliver a push notification, or raise RuntimeError on failure."""
        raise NotImplementedError


class UnconfiguredNotifier:
    """No-op notifier used when no push service is configured.

    Alerts still reach the app live over the event bus; this only governs the
    "phone push when the app is closed" channel, which stays off until set up.
    """

    name = "unconfigured"
    configured = False

    def notify(self, title: str, message: str, priority: str = "default") -> None:
        return None


class NtfyNotifier:
    """Phone push via a topic on an ntfy server (ntfy.sh or self-hosted).

    ntfy is a tiny publish/subscribe push service: POST to ``{base_url}/{topic}``
    and every device subscribed to that topic in the free ntfy app buzzes — even
    with the Odin app closed. Pick an unguessable topic; anyone who knows it can
    read the alerts, so treat it like the access token.
    """

    name = "ntfy"
    configured = True

    # ntfy's priority header is 1 (min) .. 5 (max); map the words Odin uses.
    _PRIORITY = {"min": "1", "low": "2", "default": "3", "high": "4", "urgent": "5", "max": "5"}

    def __init__(
        self,
        topic: str,
        base_url: str = "https://ntfy.sh",
        token: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        cleaned = topic.strip().strip("/")
        if not cleaned:
            raise ValueError("An ntfy topic is required")
        self.topic = cleaned
        self.base_url = base_url.rstrip("/")
        self.token = (token or "").strip() or None
        self.timeout_seconds = timeout_seconds

    def notify(self, title: str, message: str, priority: str = "default") -> None:
        headers = {
            "Title": title.encode("utf-8", "replace").decode("latin-1", "replace"),
            "Priority": self._PRIORITY.get(priority.lower(), "3"),
            "Tags": "warning",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.base_url}/{self.topic}",
            data=message.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Push notification rejected ({exc.code})") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Push notification failed: {exc}") from exc
