from __future__ import annotations

import sqlite3
from collections.abc import Callable

SCHEMA_VERSION = 3


def _migration_1(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
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
        CREATE TABLE IF NOT EXISTS reflection_summaries (
          reflection_id INTEGER PRIMARY KEY AUTOINCREMENT,
          convo_id INTEGER NOT NULL,
          summary TEXT NOT NULL,
          topics TEXT,
          sentiment TEXT,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(convo_id) REFERENCES conversations(convo_id)
        );
        CREATE TABLE IF NOT EXISTS documents (
          document_id TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL,
          source TEXT NOT NULL,
          content TEXT NOT NULL,
          embedding_id TEXT,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_convo_id_created_at
          ON messages(convo_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_tasks_user_id_status ON tasks(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_reflection_summaries_convo_id
          ON reflection_summaries(convo_id);
        CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
        """
    )


def _migration_2(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_blocks (
          label TEXT PRIMARY KEY,
          content TEXT NOT NULL DEFAULT '',
          updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def _migration_3(connection: sqlite3.Connection) -> None:
    # Temporal facts: subject-predicate-object triples with validity bounds so a
    # superseded fact (e.g. an old employer) is kept as history but stops being
    # asserted as current. A row is "currently true" when valid_to IS NULL.
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS facts (
          fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          subject TEXT NOT NULL,
          predicate TEXT NOT NULL,
          object TEXT NOT NULL,
          valid_from DATETIME DEFAULT CURRENT_TIMESTAMP,
          valid_to DATETIME,
          source TEXT,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_current
          ON facts(user_id, subject, predicate, valid_to);
        """
    )


MIGRATIONS: tuple[tuple[int, Callable[[sqlite3.Connection], None]], ...] = (
    (1, _migration_1),
    (2, _migration_2),
    (3, _migration_3),
)


def run_migrations(connection: sqlite3.Connection) -> None:
    current_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if current_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema {current_version} is newer than supported version {SCHEMA_VERSION}"
        )
    connection.execute("PRAGMA foreign_keys = ON")
    for version, migration in MIGRATIONS:
        if version <= current_version:
            continue
        migration(connection)
        connection.execute(f"PRAGMA user_version = {version}")
