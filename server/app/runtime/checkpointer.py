"""Postgres copy of the in-memory checkpointer. Each thread is one row in schema checkpoints."""

from __future__ import annotations

import pickle
import threading
from collections.abc import Sequence
from typing import Any

import psycopg
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import ChannelVersions, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.memory import InMemorySaver


def _plain_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


class PostgresThreadSaver(InMemorySaver):
    def __init__(self, database_url: str) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._conn = psycopg.connect(_plain_url(database_url), autocommit=True)
        self._conn.execute("CREATE SCHEMA IF NOT EXISTS checkpoints")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints.threads (
                thread_id text PRIMARY KEY,
                blob bytea NOT NULL
            )
            """
        )
        self._load()

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        with self._lock:
            saved = super().put(config, checkpoint, metadata, new_versions)
            self._store(saved["configurable"]["thread_id"])
            return saved

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        with self._lock:
            super().put_writes(config, writes, task_id, task_path)
            self._store(config["configurable"]["thread_id"])

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            super().delete_thread(thread_id)
            self._conn.execute("DELETE FROM checkpoints.threads WHERE thread_id = %s", (thread_id,))

    def close(self) -> None:
        self._conn.close()

    def _load(self) -> None:
        rows = self._conn.execute("SELECT thread_id, blob FROM checkpoints.threads").fetchall()
        for thread_id, blob in rows:
            payload = pickle.loads(blob)
            for namespace, checkpoints in payload["storage"].items():
                self.storage[thread_id][namespace].update(checkpoints)
            for key, writes in payload["writes"].items():
                self.writes[key].update(writes)
            self.blobs.update(payload["blobs"])

    def _store(self, thread_id: str) -> None:
        payload = {
            "storage": {namespace: dict(rows) for namespace, rows in self.storage.get(thread_id, {}).items()},
            "writes": {key: value for key, value in self.writes.items() if key[0] == thread_id},
            "blobs": {key: value for key, value in self.blobs.items() if key[0] == thread_id},
        }
        blob = pickle.dumps(payload)
        self._conn.execute(
            """
            INSERT INTO checkpoints.threads (thread_id, blob) VALUES (%s, %s)
            ON CONFLICT (thread_id) DO UPDATE SET blob = EXCLUDED.blob
            """,
            (thread_id, blob),
        )
