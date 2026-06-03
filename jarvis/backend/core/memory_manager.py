from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal


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
    def __init__(self, db_path: Path | str, cache: TTLCache | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache = cache or TTLCache()
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

    def add_message(
        self,
        convo_id: int,
        role: Literal["user", "assistant", "bot"],
        content: str,
        embedding_id: str | None = None,
    ) -> MessageRecord:
        if not content.strip():
            raise ValueError("content is required")
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
        self.cache.clear()
        return self._message_from_row(row)

    def query_messages(self, user_id: int, query: str, limit: int = 5) -> list[MessageRecord]:
        cache_key = f"{user_id}:{query}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
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
        self.cache.set(cache_key, records)
        return records

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

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS users (
                  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  display_name TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS conversations (
                  convo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  title TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                  msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  convo_id INTEGER NOT NULL,
                  role TEXT CHECK(role IN ('user','assistant','bot')) NOT NULL,
                  content TEXT NOT NULL,
                  embedding_id TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(convo_id) REFERENCES conversations(convo_id)
                );

                CREATE TABLE IF NOT EXISTS bots (
                  bot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE NOT NULL,
                  persona TEXT,
                  description TEXT
                );

                CREATE TABLE IF NOT EXISTS tasks (
                  task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  name TEXT NOT NULL,
                  description TEXT,
                  status TEXT CHECK(status IN ('pending','in_progress','complete')) NOT NULL,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_user_id
                  ON conversations(user_id);
                CREATE INDEX IF NOT EXISTS idx_messages_convo_id_created_at
                  ON messages(convo_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_user_id_status
                  ON tasks(user_id, status);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
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
