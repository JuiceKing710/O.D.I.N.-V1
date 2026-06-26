from __future__ import annotations

import json
import math
import sqlite3
import struct
import threading
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from jarvis.backend.core.lm_provider import ollama_keep_alive


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
    def delete(self, collection: str, record_id: str) -> None:
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

    def delete(self, collection: str, record_id: str) -> None:
        return None

    def health(self) -> dict[str, Any]:
        return {"enabled": False, "provider": "null"}


class OllamaEmbedder:
    """Generates embeddings through a local Ollama embedding model."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "nomic-embed-text",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.keep_alive = ollama_keep_alive()

    def __call__(self, text: str) -> list[float]:
        payload = json.dumps(
            {"model": self.model, "input": text, "keep_alive": self.keep_alive}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
            return [float(value) for value in body["embeddings"][0]]
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
        ) as exc:
            raise RuntimeError(f"Embedding request failed: {exc}") from exc


def _pack_vector(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _unpack_vector(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def _cosine_similarity_prenorm(
    left: list[float], left_norm: float, right: list[float]
) -> float:
    """Cosine similarity when the left vector's norm is already known.

    Used in the query scan so the query vector's norm is computed once rather
    than once per stored record.
    """
    if len(left) != len(right) or not left or left_norm == 0.0:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_right == 0.0:
        return 0.0
    return dot / (left_norm * norm_right)


class SqliteVectorStore(VectorStoreInterface):
    """Semantic memory stored in SQLite with local embeddings — no external services
    beyond the Ollama embedding model, and covered by the existing encrypted backups."""

    def __init__(
        self,
        db_path: Path | str,
        embedder: Callable[[str], list[float]] | None = None,
        db_lock: threading.RLock | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or OllamaEmbedder()
        # One chat turn embeds the same text up to three times (storing the user
        # message, then querying the "messages" and "documents" collections with
        # the identical query). Embeddings are deterministic per model, so a small
        # bounded cache collapses those repeats into a single network call.
        self._embed = lru_cache(maxsize=128)(self.embedder)
        self._lock = db_lock or threading.RLock()
        self.last_error: str | None = None
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vector_records (
                    record_id TEXT PRIMARY KEY,
                    collection TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    embedding BLOB NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vector_records_collection"
                " ON vector_records(collection)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5)

    @property
    def enabled(self) -> bool:
        return True

    def upsert_message(
        self, message_id: int, content: str, metadata: dict[str, Any]
    ) -> str | None:
        return self._upsert("messages", f"message:{message_id}", content, metadata)

    def upsert_document(
        self, document_id: str, content: str, metadata: dict[str, Any]
    ) -> str | None:
        return self._upsert("documents", f"document:{document_id}", content, metadata)

    def upsert_task(self, task_id: int, content: str, metadata: dict[str, Any]) -> str | None:
        return self._upsert("tasks", f"task:{task_id}", content, metadata)

    def query(self, collection: str, text: str, limit: int) -> list[VectorSearchResult]:
        if not text.strip():
            return []
        try:
            query_vector = self._embed(text)
            self.last_error = None
        except RuntimeError as exc:
            self.last_error = str(exc)
            return []
        # The query vector's norm is constant across every stored row, so compute
        # it once instead of recomputing it inside _cosine_similarity per record.
        query_norm = math.sqrt(sum(value * value for value in query_vector))
        if query_norm == 0.0:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT record_id, content, metadata, embedding FROM vector_records"
                " WHERE collection = ?",
                (collection,),
            ).fetchall()
        scored = []
        for record_id, content, metadata, blob in rows:
            score = _cosine_similarity_prenorm(query_vector, query_norm, _unpack_vector(blob))
            scored.append(
                VectorSearchResult(
                    record_id=record_id,
                    content=content,
                    metadata=json.loads(metadata),
                    score=score,
                )
            )
        scored.sort(key=lambda result: result.score or 0.0, reverse=True)
        return scored[:limit]

    def delete(self, collection: str, record_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM vector_records WHERE collection = ? AND record_id = ?",
                (collection, record_id),
            )

    def health(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            counts = dict(
                conn.execute(
                    "SELECT collection, COUNT(*) FROM vector_records GROUP BY collection"
                ).fetchall()
            )
        embed_model = getattr(self.embedder, "model", "custom")
        return {
            "enabled": True,
            "provider": "sqlite-local",
            "model": embed_model,
            "collections": counts,
            "last_error": self.last_error,
        }

    def _upsert(
        self, collection: str, record_id: str, content: str, metadata: dict[str, Any]
    ) -> str | None:
        cleaned = content.strip()
        if not cleaned:
            return None
        try:
            vector = self._embed(cleaned)
            self.last_error = None
        except RuntimeError as exc:
            self.last_error = str(exc)
            return None
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO vector_records(record_id, collection, content, metadata, embedding)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(record_id) DO UPDATE SET"
                " content = excluded.content, metadata = excluded.metadata,"
                " embedding = excluded.embedding",
                (record_id, collection, cleaned, json.dumps(metadata), _pack_vector(vector)),
            )
        return record_id


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

    def delete(self, collection: str, record_id: str) -> None:
        target = self._collections.get(collection)
        if target is not None:
            target.delete(ids=[record_id])

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

    def delete(self, collection: str, record_id: str) -> None:
        self._collections.get(collection, {}).pop(record_id, None)

    def health(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "provider": "memory",
            "collections": {
                name: len(values) for name, values in self._collections.items()
            },
        }
