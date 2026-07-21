"""Application service for local question-builder commands."""

from __future__ import annotations

from dataclasses import dataclass

from explainbench.question_builders.common.locking import WorkspaceLock
from explainbench.question_builders.common.orchestration import (
    BuilderOrchestrator,
    StageRegistry,
    StageRunSummary,
)
from explainbench.question_builders.local.config import LocalBuilderConfig
from explainbench.question_builders.local.registry import LOCAL_STAGE_REGISTRY
from explainbench.question_builders.local.submission_adapter import (
    write_predictions_file,
)
from explainbench.question_builders.local.workspace import LocalBuilderWorkspace
from explainbench.schemas import Submission


@dataclass(frozen=True)
class LocalWorkspaceStatus:
    """Read-only summary returned by the local status service."""

    submission_id: str
    submission_fingerprint: str
    instance_count: int
    stages: tuple[tuple[str, dict[str, int]], ...]
    failures: tuple[tuple[str, str, str, bool, int, int, int], ...]
    artifact_output: str | None


def _prepare_orchestrator(
    submission: Submission,
    config: LocalBuilderConfig,
    *,
    resume: bool,
    registry: StageRegistry,
) -> tuple[LocalBuilderWorkspace, BuilderOrchestrator]:
    workspace = LocalBuilderWorkspace.prepare(
        config.workspace,
        submission,
        resume=resume,
        stage_names=registry.names,
    )
    write_predictions_file(workspace.root, submission)
    orchestrator = BuilderOrchestrator(
        registry=registry,
        workspace=workspace,
        instances=submission.instances,
        submission_id=submission.submission_id,
        config=config,
        max_attempts=config.max_attempts,
        max_workers=config.max_workers,
    )
    return workspace, orchestrator


def run_local_pipeline(
    submission: Submission,
    config: LocalBuilderConfig,
    *,
    resume: bool = False,
    registry: StageRegistry = LOCAL_STAGE_REGISTRY,
) -> tuple[StageRunSummary, ...]:
    """Run the complete registered local-effect pipeline."""

    with WorkspaceLock(config.workspace):
        _, orchestrator = _prepare_orchestrator(
            submission,
            config,
            resume=resume,
            registry=registry,
        )
        return orchestrator.run_all()


def run_local_stage(
    stage_name: str,
    submission: Submission,
    config: LocalBuilderConfig,
    *,
    resume: bool = False,
    registry: StageRegistry = LOCAL_STAGE_REGISTRY,
) -> StageRunSummary:
    """Run one local-effect stage after strict prerequisite checks."""

    with WorkspaceLock(config.workspace):
        _, orchestrator = _prepare_orchestrator(
            submission,
            config,
            resume=resume,
            registry=registry,
        )
        return orchestrator.run_stage(
            stage_name,
            require_all_prerequisites=True,
        )


def inspect_local_workspace(
    workspace_path,
    *,
    registry: StageRegistry = LOCAL_STAGE_REGISTRY,
) -> LocalWorkspaceStatus:
    """Inspect durable workspace state without taking the writer lock."""

    workspace = LocalBuilderWorkspace.inspect(workspace_path)
    stages = tuple(
        (stage_name, workspace.status_counts(stage_name))
        for stage_name in registry.names
    )
    failures = []
    for status in workspace.failures():
        message = status.failure.message if status.failure is not None else "unknown"
        failures.append(
            (
                status.stage,
                status.instance_id,
                message,
                status.failure.retryable if status.failure is not None else False,
                status.retry_cycle,
                status.cycle_attempt,
                status.total_attempts,
            )
        )
    return LocalWorkspaceStatus(
        submission_id=workspace.manifest.submission_id,
        submission_fingerprint=workspace.manifest.submission_fingerprint,
        instance_count=len(workspace.manifest.instance_ids),
        stages=stages,
        failures=tuple(failures),
        artifact_output=workspace.manifest.artifact_output,
    )
