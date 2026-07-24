"""Versioned schemas for question-builder checkpoint state."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from explainbench.schemas import StrictModel


STATUS_SCHEMA_VERSION = 2
RESULT_SCHEMA_VERSION = 1
STAGE_SUMMARY_SCHEMA_VERSION = 1

StageStateName = Literal[
    "pending",
    "running",
    "completed",
    "skipped",
    "failed",
    "stale",
]

AttemptStateName = Literal[
    "running",
    "completed",
    "skipped",
    "failed",
    "interrupted",
]


def _validate_artifact_manifests(values: list[str]) -> list[str]:
    if values != sorted(set(values)):
        raise ValueError("artifact manifest paths must be sorted and unique")
    for value in values:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or ".." in path.parts
            or value != path.as_posix()
        ):
            raise ValueError(
                "artifact manifest paths must be safe relative paths"
            )
    return values


class StageFailure(StrictModel):
    """Structured information about one failed stage attempt."""

    category: str
    message: str
    retryable: bool


class InstanceStageStatus(StrictModel):
    """Durable state for one stage and submission instance."""

    schema_version: Literal[2] = STATUS_SCHEMA_VERSION
    stage: str
    instance_id: str
    state: StageStateName
    semantic_fingerprint: str | None = None
    execution_fingerprint: str | None = None
    retry_cycle: int = Field(default=0, ge=0)
    cycle_attempt: int = Field(default=0, ge=0)
    total_attempts: int = Field(default=0, ge=0)
    started_at: str | None = None
    finished_at: str | None = None
    result_file: str | None = None
    result_checksum: str | None = None
    artifact_manifests: list[str] = Field(default_factory=list)
    failure: StageFailure | None = None
    stale_reason: str | None = None

    @field_validator("artifact_manifests")
    @classmethod
    def validate_artifact_manifests(cls, values: list[str]) -> list[str]:
        return _validate_artifact_manifests(values)

    @model_validator(mode="after")
    def validate_attempt_counters(self):
        if self.cycle_attempt > self.total_attempts:
            raise ValueError("cycle_attempt cannot exceed total_attempts")
        if self.total_attempts > 0 and self.retry_cycle == 0:
            raise ValueError("retry_cycle must be positive after an attempt")
        return self


class InstanceStageAttempt(StrictModel):
    """Durable history for one execution attempt."""

    schema_version: Literal[1] = 1
    stage: str
    instance_id: str
    state: AttemptStateName
    semantic_fingerprint: str
    execution_fingerprint: str
    retry_cycle: int = Field(ge=1)
    cycle_attempt: int = Field(ge=1)
    total_attempt: int = Field(ge=1)
    started_at: str
    finished_at: str | None = None
    artifact_manifests: list[str] = Field(default_factory=list)
    failure: StageFailure | None = None

    @field_validator("artifact_manifests")
    @classmethod
    def validate_artifact_manifests(cls, values: list[str]) -> list[str]:
        return _validate_artifact_manifests(values)

    @model_validator(mode="after")
    def validate_terminal_state(self):
        terminal = self.state != "running"
        if terminal and self.finished_at is None:
            raise ValueError("a terminal attempt requires finished_at")
        if not terminal and self.finished_at is not None:
            raise ValueError("a running attempt cannot have finished_at")
        failed = self.state in {"failed", "interrupted"}
        if failed and self.failure is None:
            raise ValueError("a failed or interrupted attempt requires failure")
        if not failed and self.failure is not None:
            raise ValueError("a successful or running attempt cannot have failure")
        return self


class StoredStageResult(StrictModel):
    """Validated result envelope referenced by a completed checkpoint."""

    schema_version: Literal[1] = RESULT_SCHEMA_VERSION
    outcome: Literal["completed", "skipped"]
    data: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None

    @model_validator(mode="after")
    def require_skip_reason(self):
        if self.outcome == "skipped" and not self.reason:
            raise ValueError("a skipped stage result requires a reason")
        if self.outcome == "completed" and self.reason is not None:
            raise ValueError("a completed stage result cannot have a skip reason")
        return self


class StageCheckpointSummary(StrictModel):
    """Rebuildable aggregate metadata for one stage."""

    schema_version: Literal[1] = STAGE_SUMMARY_SCHEMA_VERSION
    stage: str
    implementation_version: str
    semantic_config_fingerprint: str
    counts: dict[str, int]
    updated_at: str
