from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: str(uuid4()))

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "type": self.type,
            "payload": _jsonable(self.payload),
            "created_at": self.created_at.isoformat(),
        }


class EventBus:
    def __init__(self, history_size: int = 100) -> None:
        self.history_size = history_size
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._history: list[Event] = []

    def publish(
        self, event_type: str, payload: dict[str, Any], *, transient: bool = False
    ) -> Event:
        event = Event(type=event_type, payload=payload)
        if not transient:
            self._history.append(event)
            if len(self._history) > self.history_size:
                self._history = self._history[-self.history_size :]
        for subscriber in list(self._subscribers):
            subscriber.put_nowait(event)
        return event

    def history(self) -> list[Event]:
        return list(self._history)

    async def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(queue)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
