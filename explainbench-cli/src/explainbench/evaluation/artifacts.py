"""Resolve and validate shared intent and model-specific effect artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ValidationError

from explainbench.evaluation.registry import TASK_SPECS, TaskName
from explainbench.evaluation.schemas import (
    AnswerGroundTruth,
    ContextArtifact,
    E2EEffectContext,
    E2EEffectGroundTruth,
    E2EIntentContext,
    GroundTruthArtifact,
    LocalEffectContext,
    LocalIntentContext,
)
from explainbench.resources import load_shared_intent_artifacts
from explainbench.submission import supported_instance_ids


class ArtifactError(ValueError):
    """Base class for evaluation artifact failures."""


class ArtifactResolutionError(ArtifactError):
    """Raised when required artifact files cannot be resolved."""


class ArtifactValidationError(ArtifactError):
    """Raised when resolved artifact contents are malformed or inconsistent."""


@dataclass(frozen=True)
class TaskArtifacts:
    task: TaskName
    context: Mapping[str, ContextArtifact]
    ground_truths: Mapping[str, GroundTruthArtifact]
    instance_ids: frozenset[str]
    context_source: str
    ground_truth_source: str


_ARTIFACT_SCHEMAS: Mapping[
    TaskName, tuple[type[BaseModel], type[BaseModel]]
] = {
    TaskName.E2E_INTENT: (E2EIntentContext, AnswerGroundTruth),
    TaskName.E2E_EFFECT: (E2EEffectContext, E2EEffectGroundTruth),
    TaskName.LOCAL_INTENT: (LocalIntentContext, AnswerGroundTruth),
    TaskName.LOCAL_EFFECT: (LocalEffectContext, AnswerGroundTruth),
}

_SAFE_SUBMISSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON value {value!r} is not allowed")


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _load_external_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ArtifactResolutionError(f"cannot read effect artifact {path}: {error}") from error
    except UnicodeError as error:
        raise ArtifactValidationError(
            f"effect artifact {path} must be UTF-8 encoded: {error}"
        ) from error

    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_fields,
            parse_constant=_reject_nonstandard_constant,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise ArtifactValidationError(
            f"effect artifact {path} is not valid JSON: {error}"
        ) from error


def _validate_mapping(
    value: Any,
    *,
    model: type[BaseModel],
    source: str,
) -> dict[str, BaseModel]:
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"{source} must contain a JSON object")
    if not value:
        raise ArtifactValidationError(f"{source} must contain at least one instance")

    results: dict[str, BaseModel] = {}
    for instance_id, payload in value.items():
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise ArtifactValidationError(
                f"{source} contains an invalid instance ID {instance_id!r}"
            )
        try:
            results[instance_id] = model.model_validate(payload)
        except ValidationError as error:
            details = error.errors(include_url=False, include_context=False)
            first = details[0]
            location = ".".join(str(part) for part in first["loc"])
            suffix = f".{location}" if location else ""
            raise ArtifactValidationError(
                f"{source}[{instance_id!r}]{suffix}: {first['msg']}"
            ) from error
    return results


def _validate_pair(
    *,
    task: TaskName,
    raw_context: Any,
    raw_ground_truths: Any,
    context_source: str,
    ground_truth_source: str,
) -> TaskArtifacts:
    context_schema, ground_truth_schema = _ARTIFACT_SCHEMAS[task]
    context = _validate_mapping(
        raw_context,
        model=context_schema,
        source=context_source,
    )
    ground_truths = _validate_mapping(
        raw_ground_truths,
        model=ground_truth_schema,
        source=ground_truth_source,
    )
    context_ids = frozenset(context)
    ground_truth_ids = frozenset(ground_truths)
    if context_ids != ground_truth_ids:
        missing_context = sorted(ground_truth_ids - context_ids)
        missing_ground_truth = sorted(context_ids - ground_truth_ids)
        raise ArtifactValidationError(
            f"{task.value} context and ground truth IDs differ; "
            f"missing context={missing_context[:3]!r}, "
            f"missing ground truth={missing_ground_truth[:3]!r}"
        )

    unexpected = sorted(context_ids - supported_instance_ids())
    if unexpected:
        raise ArtifactValidationError(
            f"{task.value} contains unsupported instance IDs: {unexpected[:3]!r}"
        )

    for instance_id in context_ids:
        choice_count = len(context[instance_id].choices)
        ground_truth = ground_truths[instance_id]
        if isinstance(ground_truth, AnswerGroundTruth):
            answers = ground_truth.answer
        else:
            answers = [ground_truth.before_answer, ground_truth.after_answer]
        out_of_range = [
            answer for answer in answers if ord(answer) - ord("a") >= choice_count
        ]
        if out_of_range:
            raise ArtifactValidationError(
                f"{ground_truth_source}[{instance_id!r}] references choices "
                f"outside the {choice_count} available options: {out_of_range!r}"
            )

    return TaskArtifacts(
        task=task,
        context=context,
        ground_truths=ground_truths,
        instance_ids=context_ids,
        context_source=context_source,
        ground_truth_source=ground_truth_source,
    )


def _parse_task(task: str | TaskName) -> TaskName:
    try:
        return TaskName(task)
    except ValueError as error:
        choices = ", ".join(item.value for item in TaskName)
        raise ValueError(f"unknown evaluation task {task!r}; choose one of: {choices}") from error


def _load_shared_artifacts(task: TaskName) -> TaskArtifacts:
    raw = load_shared_intent_artifacts(task.value)
    stem = TASK_SPECS[task].artifact_stem
    return _validate_pair(
        task=task,
        raw_context=raw.context,
        raw_ground_truths=raw.ground_truths,
        context_source=f"package:context/{stem}.json",
        ground_truth_source=f"package:ground_truths/{stem}.json",
    )


def _load_effect_artifacts(
    task: TaskName,
    *,
    submission_id: str | None,
    artifacts_dir: str | Path | None,
) -> TaskArtifacts:
    if artifacts_dir is None:
        raise ArtifactResolutionError(
            f"--artifacts-dir is required for effect task {task.value}"
        )
    if submission_id is None or not _SAFE_SUBMISSION_ID.fullmatch(submission_id):
        raise ArtifactResolutionError(
            "submission_id must contain only letters, numbers, '.', '_', and '-' "
            "when effect artifacts are selected"
        )

    stem = TASK_SPECS[task].artifact_stem
    filename = f"{stem}__{submission_id}.json"
    root = Path(artifacts_dir)
    context_path = root / "context" / filename
    ground_truth_path = root / "ground_truths" / filename
    missing = [path for path in (context_path, ground_truth_path) if not path.is_file()]
    if missing:
        expected = ", ".join(str(path) for path in missing)
        raise ArtifactResolutionError(
            f"missing required artifacts for {task.value}: {expected}"
        )

    return _validate_pair(
        task=task,
        raw_context=_load_external_json(context_path),
        raw_ground_truths=_load_external_json(ground_truth_path),
        context_source=str(context_path),
        ground_truth_source=str(ground_truth_path),
    )


def load_task_artifacts(
    task: str | TaskName,
    *,
    submission_id: str | None = None,
    artifacts_dir: str | Path | None = None,
) -> TaskArtifacts:
    """Load a packaged intent pair or an external model-specific effect pair."""

    parsed_task = _parse_task(task)
    if TASK_SPECS[parsed_task].uses_shared_artifacts:
        return _load_shared_artifacts(parsed_task)
    return _load_effect_artifacts(
        parsed_task,
        submission_id=submission_id,
        artifacts_dir=artifacts_dir,
    )
