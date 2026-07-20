"""Exclusive writer locking for question-builder workspaces."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import IO


class WorkspaceLockedError(RuntimeError):
    """Raised when another process owns a workspace writer lock."""


class WorkspaceLock:
    """Hold an advisory exclusive lock for one workspace writer."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace)
        self.path = self.workspace / "workspace.lock"
        self._file: IO[str] | None = None

    def acquire(self) -> "WorkspaceLock":
        self.workspace.mkdir(parents=True, exist_ok=True)
        lock_file = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            lock_file.seek(0)
            owner = lock_file.read().strip()
            lock_file.close()
            detail = f" ({owner})" if owner else ""
            raise WorkspaceLockedError(
                f"question-builder workspace is already in use: "
                f"{self.workspace}{detail}"
            ) from error

        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "acquired_at": datetime.now(UTC).isoformat(),
                },
                sort_keys=True,
            )
        )
        lock_file.flush()
        os.fsync(lock_file.fileno())
        self._file = lock_file
        return self

    def release(self) -> None:
        if self._file is None:
            return
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None

    def __enter__(self) -> "WorkspaceLock":
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()

