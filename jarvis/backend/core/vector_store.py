from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    record_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float | None = None


class VectorStoreInterface(ABC):
    @property
    @abstractmethod
    def enabled(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def upsert_message(
        self, message_id: int, content: str, metadata: dict[str, Any]
    ) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def upsert_document(
        self, document_id: str, content: str, metadata: dict[str, Any]
    ) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def upsert_task(self, task_id: int, content: str, metadata: dict[str, Any]) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def query(self, collection: str, text: str, limit: int) -> list[VectorSearchResult]:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError


class NullVectorStore(VectorStoreInterface):
    @property
    def enabled(self) -> bool:
        return False

    def upsert_message(
        self, message_id: int, content: str, metadata: dict[str, Any]
    ) -> str | None:
        return None

    def upsert_document(
        self, document_id: str, content: str, metadata: dict[str, Any]
    ) -> str | None:
        return None

    def upsert_task(self, task_id: int, content: str, metadata: dict[str, Any]) -> str | None:
        return None

    def query(self, collection: str, text: str, limit: int) -> list[VectorSearchResult]:
        return []

    def health(self) -> dict[str, Any]:
        return {"enabled": False, "provider": "null"}


class ChromaVectorStore(VectorStoreInterface):
    def __init__(self, persist_path: Path | str) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("ChromaDB is not installed") from exc

        self.persist_path = Path(persist_path)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_path))
        self._collections = {
            name: self._client.get_or_create_collection(name=name)
            for name in ("messages", "documents", "tasks")
        }

    @property
    def enabled(self) -> bool:
        return True

    def upsert_message(
        self, message_id: int, content: str, metadata: dict[str, Any]
    ) -> str | None:
        record_id = f"message:{message_id}"
        self._upsert("messages", record_id, content, metadata)
        return record_id

    def upsert_document(
        self, document_id: str, content: str, metadata: dict[str, Any]
    ) -> str | None:
        record_id = f"document:{document_id}"
        self._upsert("documents", record_id, content, metadata)
        return record_id

    def upsert_task(self, task_id: int, content: str, metadata: dict[str, Any]) -> str | None:
        record_id = f"task:{task_id}"
        self._upsert("tasks", record_id, content, metadata)
        return record_id

    def query(self, collection: str, text: str, limit: int) -> list[VectorSearchResult]:
        target = self._collections.get(collection)
        if target is None or not text.strip():
            return []
        result = target.query(query_texts=[text], n_results=limit)
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0] if result.get("distances") else []
        rows: list[VectorSearchResult] = []
        for index, record_id in enumerate(ids):
            distance = distances[index] if index < len(distances) else None
            rows.append(
                VectorSearchResult(
                    record_id=record_id,
                    content=documents[index] if index < len(documents) else "",
                    metadata=metadatas[index] if index < len(metadatas) else {},
                    score=float(distance) if distance is not None else None,
                )
            )
        return rows

    def health(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "provider": "chromadb",
            "path": str(self.persist_path),
            "collections": sorted(self._collections),
        }

    def _upsert(self, collection: str, record_id: str, content: str, metadata: dict[str, Any]) -> None:
        self._collections[collection].upsert(
            ids=[record_id],
            documents=[content],
            metadatas=[metadata],
        )


class InMemoryVectorStore(VectorStoreInterface):
    def __init__(self) -> None:
        self._collections: dict[str, dict[str, VectorSearchResult]] = {
            "messages": {},
            "documents": {},
            "tasks": {},
        }

    @property
    def enabled(self) -> bool:
        return True

    def upsert_message(
        self, message_id: int, content: str, metadata: dict[str, Any]
    ) -> str | None:
        record_id = f"message:{message_id}"
        self._collections["messages"][record_id] = VectorSearchResult(
            record_id=record_id, content=content, metadata=dict(metadata)
        )
        return record_id

    def upsert_document(
        self, document_id: str, content: str, metadata: dict[str, Any]
    ) -> str | None:
        record_id = f"document:{document_id}"
        self._collections["documents"][record_id] = VectorSearchResult(
            record_id=record_id, content=content, metadata=dict(metadata)
        )
        return record_id

    def upsert_task(self, task_id: int, content: str, metadata: dict[str, Any]) -> str | None:
        record_id = f"task:{task_id}"
        self._collections["tasks"][record_id] = VectorSearchResult(
            record_id=record_id, content=content, metadata=dict(metadata)
        )
        return record_id

    def query(self, collection: str, text: str, limit: int) -> list[VectorSearchResult]:
        words = {word.lower() for word in text.split() if word.strip()}
        if not words:
            return []
        rows = []
        for item in self._collections.get(collection, {}).values():
            haystack = set(item.content.lower().split())
            overlap = len(words & haystack)
            if overlap:
                rows.append(
                    VectorSearchResult(
                        record_id=item.record_id,
                        content=item.content,
                        metadata=item.metadata,
                        score=float(overlap),
                    )
                )
        rows.sort(key=lambda row: row.score or 0.0, reverse=True)
        return rows[:limit]

    def health(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "provider": "memory",
            "collections": {
                name: len(values) for name, values in self._collections.items()
            },
        }
