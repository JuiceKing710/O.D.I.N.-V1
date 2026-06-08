from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal

from jarvis.backend.core.vector_store import NullVectorStore, VectorStoreInterface
from jarvis.backend.core.migrations import run_migrations


@dataclass(slots=True)
class UserRecord:
    user_id: int
    username: str
    display_name: str | None
    created_at: datetime


@dataclass(slots=True)
class ConversationRecord:
    convo_id: int
    user_id: int
    started_at: datetime
    title: str | None


@dataclass(slots=True)
class ConversationSummaryRecord:
    convo_id: int
    user_id: int
    started_at: datetime
    title: str | None
    message_count: int
    last_activity_at: datetime

    def to_api(self) -> dict[str, Any]:
        return {
            "convo_id": self.convo_id,
            "user_id": self.user_id,
            "started_at": self.started_at,
            "title": self.title,
            "message_count": self.message_count,
            "last_activity_at": self.last_activity_at,
        }


@dataclass(slots=True)
class MessageRecord:
    msg_id: int
    convo_id: int
    role: str
    content: str
    embedding_id: str | None
    created_at: datetime

    def to_api(self) -> dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "convo_id": self.convo_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class TaskRecord:
    task_id: int
    user_id: int
    name: str
    description: str | None
    status: Literal["pending", "in_progress", "complete"]
    created_at: datetime

    def to_api(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class ReflectionRecord:
    reflection_id: int
    convo_id: int
    summary: str
    topics: str | None
    sentiment: str | None
    created_at: datetime

    def to_api(self) -> dict[str, Any]:
        return {
            "reflection_id": self.reflection_id,
            "convo_id": self.convo_id,
            "summary": self.summary,
            "topics": self.topics,
            "sentiment": self.sentiment,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class DocumentRecord:
    document_id: str
    user_id: int
    source: str
    content: str
    embedding_id: str | None
    created_at: datetime

    def to_api(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "user_id": self.user_id,
            "source": self.source,
            "content": self.content,
            "created_at": self.created_at,
        }


class TTLCache:
    def __init__(self, ttl_seconds: int = 300, max_size: int = 256) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._values: dict[str, tuple[float, list[MessageRecord]]] = {}

    def get(self, key: str) -> list[MessageRecord] | None:
        item = self._values.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key: str, value: list[MessageRecord]) -> None:
        if len(self._values) >= self.max_size:
            oldest = min(self._values, key=lambda current: self._values[current][0])
            self._values.pop(oldest, None)
        self._values[key] = (time.time() + self.ttl_seconds, value)

    def clear(self) -> None:
        self._values.clear()


class MemoryManager:
    def __init__(
        self,
        db_path: Path | str,
        cache: TTLCache | None = None,
        vector_store: VectorStoreInterface | None = None,
        db_lock: threading.RLock | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache = cache or TTLCache()
        self.vector_store = vector_store or NullVectorStore()
        self.db_lock = db_lock or threading.RLock()
        self._initialize()

    def get_or_create_user(self, username: str, display_name: str | None = None) -> UserRecord:
        cleaned = username.strip()
        if not cleaned:
            raise ValueError("username is required")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(username, display_name) VALUES (?, ?)",
                (cleaned, display_name),
            )
            row = conn.execute(
                "SELECT user_id, username, display_name, created_at FROM users WHERE username = ?",
                (cleaned,),
            ).fetchone()
        return self._user_from_row(row)

    def create_conversation(self, user_id: int, title: str | None = None) -> ConversationRecord:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations(user_id, title) VALUES (?, ?)", (user_id, title)
            )
            row = conn.execute(
                "SELECT convo_id, user_id, started_at, title FROM conversations WHERE convo_id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._conversation_from_row(row)

    def get_conversation(self, convo_id: int, user_id: int) -> ConversationRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT convo_id, user_id, started_at, title
                FROM conversations
                WHERE convo_id = ? AND user_id = ?
                """,
                (convo_id, user_id),
            ).fetchone()
        if row is None:
            raise ValueError(f"Conversation not found: {convo_id}")
        return self._conversation_from_row(row)

    def list_conversations(self, user_id: int, limit: int = 25) -> list[ConversationSummaryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  c.convo_id,
                  c.user_id,
                  c.started_at,
                  c.title,
                  COUNT(m.msg_id) AS message_count,
                  COALESCE(MAX(m.created_at), c.started_at) AS last_activity_at
                FROM conversations c
                LEFT JOIN messages m ON m.convo_id = c.convo_id
                WHERE c.user_id = ?
                GROUP BY c.convo_id, c.user_id, c.started_at, c.title
                ORDER BY last_activity_at DESC, c.convo_id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._conversation_summary_from_row(row) for row in rows]

    def add_message(
        self,
        convo_id: int,
        role: Literal["user", "assistant", "bot"],
        content: str,
        embedding_id: str | None = None,
    ) -> MessageRecord:
        if not content.strip():
            raise ValueError("content is required")
        embedding_id = None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages(convo_id, role, content, embedding_id)
                VALUES (?, ?, ?, ?)
                """,
                (convo_id, role, content, embedding_id),
            )
            row = conn.execute(
                """
                SELECT msg_id, convo_id, role, content, embedding_id, created_at
                FROM messages
                WHERE msg_id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            message = self._message_from_row(row)
            embedding_id = self._safe_upsert_message(message)
            if embedding_id is not None:
                conn.execute(
                    "UPDATE messages SET embedding_id = ? WHERE msg_id = ?",
                    (embedding_id, message.msg_id),
                )
                row = conn.execute(
                    """
                    SELECT msg_id, convo_id, role, content, embedding_id, created_at
                    FROM messages
                    WHERE msg_id = ?
                    """,
                    (message.msg_id,),
                ).fetchone()
        self.cache.clear()
        return self._message_from_row(row)

    def query_messages(self, user_id: int, query: str, limit: int = 5) -> list[MessageRecord]:
        cache_key = f"{user_id}:{query}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        vector_records = self._query_vector_messages(user_id, query, limit)
        if len(vector_records) >= limit:
            self.cache.set(cache_key, vector_records)
            return vector_records
        needle = f"%{query.strip()}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.msg_id, m.convo_id, m.role, m.content, m.embedding_id, m.created_at
                FROM messages m
                JOIN conversations c ON c.convo_id = m.convo_id
                WHERE c.user_id = ? AND m.content LIKE ?
                ORDER BY m.created_at DESC, m.msg_id DESC
                LIMIT ?
                """,
                (user_id, needle, limit),
            ).fetchall()
        records = [self._message_from_row(row) for row in rows]
        merged = self._merge_messages(vector_records, records, limit)
        self.cache.set(cache_key, merged)
        return merged

    def save_document(
        self,
        user_id: int,
        document_id: str,
        source: str,
        content: str,
    ) -> DocumentRecord:
        cleaned_id = document_id.strip()
        cleaned_content = content.strip()
        if not cleaned_id or not cleaned_content:
            raise ValueError("document_id and content are required")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents(document_id, user_id, source, content)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                  user_id = excluded.user_id,
                  source = excluded.source,
                  content = excluded.content
                """,
                (cleaned_id, user_id, source.strip() or "unknown", cleaned_content),
            )
            row = conn.execute(
                """
                SELECT document_id, user_id, source, content, embedding_id, created_at
                FROM documents
                WHERE document_id = ?
                """,
                (cleaned_id,),
            ).fetchone()
            document = self._document_from_row(row)
            embedding_id = self._safe_upsert_document(document)
            if embedding_id is not None:
                conn.execute(
                    "UPDATE documents SET embedding_id = ? WHERE document_id = ?",
                    (embedding_id, cleaned_id),
                )
                row = conn.execute(
                    """
                    SELECT document_id, user_id, source, content, embedding_id, created_at
                    FROM documents
                    WHERE document_id = ?
                    """,
                    (cleaned_id,),
                ).fetchone()
        self.cache.clear()
        return self._document_from_row(row)

    def query_documents(self, user_id: int, query: str, limit: int = 5) -> list[DocumentRecord]:
        vector_records = self._query_vector_documents(user_id, query, limit)
        if len(vector_records) >= limit:
            return vector_records
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT document_id, user_id, source, content, embedding_id, created_at
                FROM documents
                WHERE user_id = ? AND content LIKE ?
                ORDER BY created_at DESC, document_id DESC
                LIMIT ?
                """,
                (user_id, f"%{query.strip()}%", limit),
            ).fetchall()
        merged = []
        seen = set()
        for document in [*vector_records, *(self._document_from_row(row) for row in rows)]:
            if document.document_id in seen:
                continue
            merged.append(document)
            seen.add(document.document_id)
            if len(merged) >= limit:
                break
        return merged

    def query_context(self, user_id: int, query: str, limit: int = 5) -> list[str]:
        messages = self.query_messages(user_id, query, limit)
        documents = self.query_documents(user_id, query, limit)
        context = [f"[{document.source}] {document.content}" for document in documents]
        context.extend(message.content for message in messages)
        return context[:limit]

    def create_task(self, user_id: int, name: str, description: str | None = None) -> TaskRecord:
        if not name.strip():
            raise ValueError("task name is required")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks(user_id, name, description, status)
                VALUES (?, ?, ?, 'pending')
                """,
                (user_id, name.strip(), description),
            )
            row = conn.execute(
                """
                SELECT task_id, user_id, name, description, status, created_at
                FROM tasks
                WHERE task_id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            task = self._task_from_row(row)
            self._safe_upsert_task(task)
        return self._task_from_row(row)

    def list_tasks(self, user_id: int) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, user_id, name, description, status, created_at
                FROM tasks
                WHERE user_id = ?
                ORDER BY created_at DESC, task_id DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def update_task(
        self,
        user_id: int,
        task_id: int,
        *,
        description: str | None = None,
        name: str | None = None,
        status: Literal["pending", "in_progress", "complete"] | None = None,
    ) -> TaskRecord:
        updates = []
        values = []
        if name is not None:
            if not name.strip():
                raise ValueError("task name is required")
            updates.append("name = ?")
            values.append(name.strip())
        if description is not None:
            updates.append("description = ?")
            values.append(description.strip() or None)
        if status is not None:
            if status not in {"pending", "in_progress", "complete"}:
                raise ValueError(f"Invalid task status: {status}")
            updates.append("status = ?")
            values.append(status)
        if not updates:
            raise ValueError("No task updates provided")
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE tasks
                SET {", ".join(updates)}
                WHERE task_id = ? AND user_id = ?
                """,
                (*values, task_id, user_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Task not found: {task_id}")
            row = conn.execute(
                """
                SELECT task_id, user_id, name, description, status, created_at
                FROM tasks
                WHERE task_id = ? AND user_id = ?
                """,
                (task_id, user_id),
            ).fetchone()
            task = self._task_from_row(row)
            self._safe_upsert_task(task)
        return task

    def list_conversation_messages(self, convo_id: int) -> list[MessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT msg_id, convo_id, role, content, embedding_id, created_at
                FROM messages
                WHERE convo_id = ?
                ORDER BY created_at ASC, msg_id ASC
                """,
                (convo_id,),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def delete_conversation(self, user_id: int, convo_id: int) -> None:
        self.get_conversation(convo_id, user_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT msg_id FROM messages WHERE convo_id = ?", (convo_id,)
            ).fetchall()
            conn.execute("DELETE FROM reflection_summaries WHERE convo_id = ?", (convo_id,))
            conn.execute("DELETE FROM messages WHERE convo_id = ?", (convo_id,))
            conn.execute(
                "DELETE FROM conversations WHERE convo_id = ? AND user_id = ?",
                (convo_id, user_id),
            )
        for row in rows:
            self.vector_store.delete("messages", f"message:{row['msg_id']}")
        self.cache.clear()

    def delete_task(self, user_id: int, task_id: int) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE task_id = ? AND user_id = ?", (task_id, user_id)
            )
        if cursor.rowcount == 0:
            raise ValueError(f"Task not found: {task_id}")
        self.vector_store.delete("tasks", f"task:{task_id}")

    def list_documents(self, user_id: int) -> list[DocumentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT document_id, user_id, source, content, embedding_id, created_at
                FROM documents
                WHERE user_id = ?
                ORDER BY created_at DESC, document_id DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._document_from_row(row) for row in rows]

    def delete_document(self, user_id: int, document_id: str) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE document_id = ? AND user_id = ?",
                (document_id, user_id),
            )
        if cursor.rowcount == 0:
            raise ValueError(f"Document not found: {document_id}")
        self.vector_store.delete("documents", f"document:{document_id}")

    def save_reflection_summary(
        self,
        convo_id: int,
        summary: str,
        topics: str | None = None,
        sentiment: str | None = None,
    ) -> ReflectionRecord:
        if not summary.strip():
            raise ValueError("summary is required")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reflection_summaries(convo_id, summary, topics, sentiment)
                VALUES (?, ?, ?, ?)
                """,
                (convo_id, summary.strip(), topics, sentiment),
            )
            row = conn.execute(
                """
                SELECT reflection_id, convo_id, summary, topics, sentiment, created_at
                FROM reflection_summaries
                WHERE reflection_id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return self._reflection_from_row(row)

    def list_reflection_summaries(self, convo_id: int) -> list[ReflectionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT reflection_id, convo_id, summary, topics, sentiment, created_at
                FROM reflection_summaries
                WHERE convo_id = ?
                ORDER BY created_at DESC, reflection_id DESC
                """,
                (convo_id,),
            ).fetchall()
        return [self._reflection_from_row(row) for row in rows]

    def _initialize(self) -> None:
        with self._connect() as conn:
            run_migrations(conn)

    def _query_vector_messages(
        self, user_id: int, query: str, limit: int
    ) -> list[MessageRecord]:
        if not self.vector_store.enabled or not query.strip():
            return []
        try:
            vector_rows = self.vector_store.query("messages", query, limit)
        except Exception:
            return []
        message_ids = []
        for row in vector_rows:
            raw_id = row.metadata.get("msg_id")
            if raw_id is None and row.record_id.startswith("message:"):
                raw_id = row.record_id.split(":", maxsplit=1)[1]
            try:
                message_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        if not message_ids:
            return []
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in message_ids)
            rows = conn.execute(
                f"""
                SELECT m.msg_id, m.convo_id, m.role, m.content, m.embedding_id, m.created_at
                FROM messages m
                JOIN conversations c ON c.convo_id = m.convo_id
                WHERE c.user_id = ? AND m.msg_id IN ({placeholders})
                """,
                (user_id, *message_ids),
            ).fetchall()
        records_by_id = {row["msg_id"]: self._message_from_row(row) for row in rows}
        return [records_by_id[msg_id] for msg_id in message_ids if msg_id in records_by_id]

    def _query_vector_documents(
        self, user_id: int, query: str, limit: int
    ) -> list[DocumentRecord]:
        if not self.vector_store.enabled or not query.strip():
            return []
        try:
            vector_rows = self.vector_store.query("documents", query, limit)
        except Exception:
            return []
        document_ids = [
            str(row.metadata.get("document_id") or row.record_id.removeprefix("document:"))
            for row in vector_rows
        ]
        if not document_ids:
            return []
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in document_ids)
            rows = conn.execute(
                f"""
                SELECT document_id, user_id, source, content, embedding_id, created_at
                FROM documents
                WHERE user_id = ? AND document_id IN ({placeholders})
                """,
                (user_id, *document_ids),
            ).fetchall()
        records_by_id = {row["document_id"]: self._document_from_row(row) for row in rows}
        return [
            records_by_id[document_id]
            for document_id in document_ids
            if document_id in records_by_id
        ]

    @staticmethod
    def _merge_messages(
        primary: list[MessageRecord], secondary: list[MessageRecord], limit: int
    ) -> list[MessageRecord]:
        merged = []
        seen = set()
        for message in [*primary, *secondary]:
            if message.msg_id in seen:
                continue
            merged.append(message)
            seen.add(message.msg_id)
            if len(merged) >= limit:
                break
        return merged

    def _safe_upsert_message(self, message: MessageRecord) -> str | None:
        if not self.vector_store.enabled:
            return None
        try:
            return self.vector_store.upsert_message(
                message.msg_id,
                message.content,
                {
                    "msg_id": message.msg_id,
                    "convo_id": message.convo_id,
                    "role": message.role,
                    "timestamp": message.created_at.isoformat(),
                },
            )
        except Exception:
            return None

    def _safe_upsert_task(self, task: TaskRecord) -> str | None:
        if not self.vector_store.enabled:
            return None
        content = f"{task.name}\n{task.description or ''}".strip()
        try:
            return self.vector_store.upsert_task(
                task.task_id,
                content,
                {
                    "task_id": task.task_id,
                    "user_id": task.user_id,
                    "status": task.status,
                    "timestamp": task.created_at.isoformat(),
                },
            )
        except Exception:
            return None

    def _safe_upsert_document(self, document: DocumentRecord) -> str | None:
        if not self.vector_store.enabled:
            return None
        try:
            return self.vector_store.upsert_document(
                document.document_id,
                document.content,
                {
                    "document_id": document.document_id,
                    "user_id": document.user_id,
                    "source": document.source,
                    "timestamp": document.created_at.isoformat(),
                },
            )
        except Exception:
            return None

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self.db_lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @classmethod
    def _user_from_row(cls, row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            user_id=row["user_id"],
            username=row["username"],
            display_name=row["display_name"],
            created_at=cls._parse_datetime(row["created_at"]),
        )

    @classmethod
    def _conversation_from_row(cls, row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            convo_id=row["convo_id"],
            user_id=row["user_id"],
            started_at=cls._parse_datetime(row["started_at"]),
            title=row["title"],
        )

    @classmethod
    def _conversation_summary_from_row(cls, row: sqlite3.Row) -> ConversationSummaryRecord:
        return ConversationSummaryRecord(
            convo_id=row["convo_id"],
            user_id=row["user_id"],
            started_at=cls._parse_datetime(row["started_at"]),
            title=row["title"],
            message_count=row["message_count"],
            last_activity_at=cls._parse_datetime(row["last_activity_at"]),
        )

    @classmethod
    def _message_from_row(cls, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            msg_id=row["msg_id"],
            convo_id=row["convo_id"],
            role=row["role"],
            content=row["content"],
            embedding_id=row["embedding_id"],
            created_at=cls._parse_datetime(row["created_at"]),
        )

    @classmethod
    def _task_from_row(cls, row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            status=row["status"],
            created_at=cls._parse_datetime(row["created_at"]),
        )

    @classmethod
    def _reflection_from_row(cls, row: sqlite3.Row) -> ReflectionRecord:
        return ReflectionRecord(
            reflection_id=row["reflection_id"],
            convo_id=row["convo_id"],
            summary=row["summary"],
            topics=row["topics"],
            sentiment=row["sentiment"],
            created_at=cls._parse_datetime(row["created_at"]),
        )

    @classmethod
    def _document_from_row(cls, row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            document_id=row["document_id"],
            user_id=row["user_id"],
            source=row["source"],
            content=row["content"],
            embedding_id=row["embedding_id"],
            created_at=cls._parse_datetime(row["created_at"]),
        )
