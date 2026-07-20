"""Versioned schemas for question-builder checkpoint state."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from explainbench.schemas import StrictModel


CHECKPOINT_SCHEMA_VERSION = 1

StageStateName = Literal[
    "pending",
    "running",
    "completed",
    "skipped",
    "failed",
    "stale",
]


class StageFailure(StrictModel):
    """Structured information about one failed stage attempt."""

    category: str
    message: str
    retryable: bool


class InstanceStageStatus(StrictModel):
    """Durable state for one stage and submission instance."""

    schema_version: Literal[1] = CHECKPOINT_SCHEMA_VERSION
    stage: str
    instance_id: str
    state: StageStateName
    fingerprint: str | None = None
    attempts: int = Field(default=0, ge=0)
    started_at: str | None = None
    finished_at: str | None = None
    result_file: str | None = None
    result_checksum: str | None = None
    failure: StageFailure | None = None
    stale_reason: str | None = None


class StoredStageResult(StrictModel):
    """Validated result envelope referenced by a completed checkpoint."""

    schema_version: Literal[1] = CHECKPOINT_SCHEMA_VERSION
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

    schema_version: Literal[1] = CHECKPOINT_SCHEMA_VERSION
    stage: str
    implementation_version: str
    semantic_config_fingerprint: str
    counts: dict[str, int]
    updated_at: str

