"""Run canonical question-builder commands with durable attempt logs."""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from explainbench.question_builders.common.atomic_files import atomic_write_json
from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
)


@dataclass(frozen=True)
class CanonicalCommandResult:
    """Files and exit status produced by one canonical command."""

    command: tuple[str, ...]
    return_code: int
    stdout_path: Path
    stderr_path: Path


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    process.wait()


def run_command(
    command: Sequence[str],
    context: StageContext,
    *,
    timeout: int | None,
    cwd: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    retryable_nonzero: bool = False,
) -> CanonicalCommandResult:
    """Run one command and preserve its command record, stdout, and stderr."""

    normalized = tuple(str(part) for part in command)
    if not normalized:
        raise ValueError("command must not be empty")
    if timeout is not None and timeout < 1:
        raise ValueError("timeout must be positive")

    context.attempt_directory.mkdir(parents=True, exist_ok=True)
    context.log_directory.mkdir(parents=True, exist_ok=True)
    record_path = context.attempt_directory / "command.json"
    stdout_path = context.log_directory / "stdout.log"
    stderr_path = context.log_directory / "stderr.log"
    record = {
        "schema_version": 1,
        "command": list(normalized),
        "cwd": str(cwd) if cwd is not None else None,
        "timeout_seconds": timeout,
        "started_at": _now(),
        "finished_at": None,
        "state": "running",
        "return_code": None,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }
    atomic_write_json(record_path, record)

    process_environment = os.environ.copy()
    if environment is not None:
        process_environment.update(environment)

    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                normalized,
                cwd=cwd,
                env=process_environment,
                stdout=stdout,
                stderr=stderr,
                start_new_session=os.name == "posix",
            )
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as error:
                _terminate_process(process)
                record.update(
                    {
                        "finished_at": _now(),
                        "state": "timed_out",
                        "return_code": process.returncode,
                    }
                )
                atomic_write_json(record_path, record)
                raise StageExecutionError(
                    f"canonical command timed out after {timeout} seconds; "
                    f"see {stderr_path}",
                    category="canonical_command_timeout",
                    retryable=True,
                ) from error
            except BaseException:
                _terminate_process(process)
                record.update(
                    {
                        "finished_at": _now(),
                        "state": "interrupted",
                        "return_code": process.returncode,
                    }
                )
                atomic_write_json(record_path, record)
                raise
    except StageExecutionError:
        raise
    except OSError as error:
        record.update(
            {
                "finished_at": _now(),
                "state": "start_failed",
                "return_code": None,
            }
        )
        atomic_write_json(record_path, record)
        raise StageExecutionError(
            f"cannot start canonical command: {error}",
            category="canonical_command_start_failed",
            retryable=False,
        ) from error

    record.update(
        {
            "finished_at": _now(),
            "state": "completed" if return_code == 0 else "failed",
            "return_code": return_code,
        }
    )
    atomic_write_json(record_path, record)
    if return_code != 0:
        raise StageExecutionError(
            f"canonical command exited with status {return_code}; "
            f"see {stderr_path}",
            category="canonical_command_failed",
            retryable=retryable_nonzero,
        )
    return CanonicalCommandResult(
        command=normalized,
        return_code=return_code,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def run_canonical_module(
    module: str,
    arguments: Sequence[str],
    context: StageContext,
    *,
    timeout: int | None,
    cwd: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    retryable_nonzero: bool = False,
) -> CanonicalCommandResult:
    """Run a canonical Python module with the active interpreter."""

    if not module.strip():
        raise ValueError("module must not be blank")
    return run_command(
        (sys.executable, "-P", "-m", module, *arguments),
        context,
        timeout=timeout,
        cwd=cwd,
        environment=environment,
        retryable_nonzero=retryable_nonzero,
    )
