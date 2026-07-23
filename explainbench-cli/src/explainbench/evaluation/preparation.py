"""Prepare a submission and its selected artifacts for later inference."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from explainbench.evaluation.artifacts import TaskArtifacts, load_task_artifacts
from explainbench.evaluation.registry import TASK_SPECS, TaskName, TaskSelection, TaskSpec
from explainbench.schemas import Submission
from explainbench.submission import ValidationProfile, validate_submission


class EvaluationPreparationError(ValueError):
    """Raised when a selected task has no instances that can be evaluated."""


@dataclass(frozen=True)
class PreparedTask:
    spec: TaskSpec
    artifacts: TaskArtifacts
    evaluable_instance_ids: tuple[str, ...]
    missing_instance_ids: tuple[str, ...]


@dataclass(frozen=True)
class PreparedEvaluation:
    submission: Submission
    selection: TaskSelection
    tasks: Mapping[TaskName, PreparedTask]


def prepare_evaluation(
    submission: Submission,
    selection: TaskSelection,
    *,
    artifacts_dir: str | Path | None = None,
) -> PreparedEvaluation:
    """Validate and join a submission with every selected task artifact pair."""

    profile = (
        ValidationProfile.EFFECT
        if selection.requires_patches
        else ValidationProfile.LITE
    )
    validate_submission(submission, profile=profile)

    submitted_ids = tuple(instance.instance_id for instance in submission.instances)
    prepared: dict[TaskName, PreparedTask] = {}
    for task in selection.tasks:
        artifacts = load_task_artifacts(
            task,
            submission_id=submission.submission_id,
            artifacts_dir=artifacts_dir,
        )
        evaluable = tuple(
            instance_id
            for instance_id in submitted_ids
            if instance_id in artifacts.instance_ids
        )
        missing = tuple(
            instance_id
            for instance_id in submitted_ids
            if instance_id not in artifacts.instance_ids
        )
        if not evaluable:
            raise EvaluationPreparationError(
                f"task {task.value} has no artifacts for any submitted instance"
            )
        prepared[task] = PreparedTask(
            spec=TASK_SPECS[task],
            artifacts=artifacts,
            evaluable_instance_ids=evaluable,
            missing_instance_ids=missing,
        )

    return PreparedEvaluation(
        submission=submission,
        selection=selection,
        tasks=prepared,
    )
