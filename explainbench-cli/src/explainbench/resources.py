"""Load benchmark-owned resources distributed with ExplainBench."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Literal, Mapping


SharedIntentTask = Literal["e2e.intent", "local.intent"]

_SHARED_INTENT_STEMS: dict[SharedIntentTask, str] = {
    "e2e.intent": "e2e_intent",
    "local.intent": "local_intent",
}


class ResourceValidationError(ValueError):
    """Raised when a packaged ExplainBench resource is missing or malformed."""


@dataclass(frozen=True)
class SharedIntentArtifacts:
    """Context and ground truth for one benchmark-owned intent task."""

    task: SharedIntentTask
    context: Mapping[str, Mapping[str, Any]]
    ground_truths: Mapping[str, Mapping[str, Any]]
    instance_ids: frozenset[str]


def _resource(*parts: str):
    resource = files("explainbench")
    for part in ("data", *parts):
        resource = resource.joinpath(part)
    return resource


def _load_json_resource(*parts: str) -> Any:
    resource = _resource(*parts)
    try:
        return json.loads(resource.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ResourceValidationError(
            f"packaged resource is missing: {'/'.join(parts)}"
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ResourceValidationError(
            f"cannot read packaged resource {'/'.join(parts)}: {error}"
        ) from error


def _load_instance_mapping(*parts: str) -> dict[str, dict[str, Any]]:
    value = _load_json_resource(*parts)
    if not isinstance(value, dict):
        raise ResourceValidationError(
            f"packaged resource {'/'.join(parts)} must contain a JSON object"
        )

    invalid_ids = [key for key, item in value.items() if not isinstance(item, dict)]
    if invalid_ids:
        preview = ", ".join(repr(key) for key in invalid_ids[:3])
        raise ResourceValidationError(
            f"packaged resource {'/'.join(parts)} has non-object entries for {preview}"
        )
    return value


def _benchmark_instance_ids() -> frozenset[str]:
    value = _load_json_resource("benchmark_instance_ids.json")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ResourceValidationError(
            "packaged resource benchmark_instance_ids.json must contain a list of strings"
        )
    if len(value) != len(set(value)):
        raise ResourceValidationError(
            "packaged resource benchmark_instance_ids.json contains duplicate IDs"
        )
    return frozenset(value)


def load_shared_intent_artifacts(task: str) -> SharedIntentArtifacts:
    """Load and validate one shared intent context/ground-truth pair."""

    if task not in _SHARED_INTENT_STEMS:
        supported = ", ".join(_SHARED_INTENT_STEMS)
        raise ValueError(f"unknown shared intent task {task!r}; choose one of: {supported}")

    typed_task: SharedIntentTask = task
    stem = _SHARED_INTENT_STEMS[typed_task]
    context = _load_instance_mapping("context", f"{stem}.json")
    ground_truths = _load_instance_mapping("ground_truths", f"{stem}.json")
    context_ids = frozenset(context)
    ground_truth_ids = frozenset(ground_truths)

    if context_ids != ground_truth_ids:
        missing_context = sorted(ground_truth_ids - context_ids)
        missing_ground_truth = sorted(context_ids - ground_truth_ids)
        raise ResourceValidationError(
            f"{task} context and ground truth IDs differ; "
            f"missing context={missing_context[:3]!r}, "
            f"missing ground truth={missing_ground_truth[:3]!r}"
        )

    benchmark_ids = _benchmark_instance_ids()
    if context_ids != benchmark_ids:
        missing = sorted(benchmark_ids - context_ids)
        unexpected = sorted(context_ids - benchmark_ids)
        raise ResourceValidationError(
            f"{task} IDs do not match the packaged benchmark IDs; "
            f"missing={missing[:3]!r}, unexpected={unexpected[:3]!r}"
        )

    return SharedIntentArtifacts(
        task=typed_task,
        context=context,
        ground_truths=ground_truths,
        instance_ids=context_ids,
    )
