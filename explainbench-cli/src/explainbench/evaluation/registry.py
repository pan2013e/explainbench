"""Canonical evaluation tasks and mode presets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Mapping, Sequence


class TaskName(StrEnum):
    E2E_INTENT = "e2e.intent"
    E2E_EFFECT = "e2e.effect"
    LOCAL_INTENT = "local.intent"
    LOCAL_EFFECT = "local.effect"


class EvaluationMode(StrEnum):
    LITE = "lite"
    FULL = "full"


@dataclass(frozen=True)
class TaskSpec:
    """Static metadata used to resolve and validate an evaluation task."""

    name: TaskName
    artifact_stem: str
    scope: Literal["e2e", "local"]
    dimension: Literal["intent", "effect"]

    @property
    def uses_shared_artifacts(self) -> bool:
        return self.dimension == "intent"


TASK_SPECS: Mapping[TaskName, TaskSpec] = MappingProxyType(
    {
        TaskName.E2E_INTENT: TaskSpec(
            name=TaskName.E2E_INTENT,
            artifact_stem="e2e_intent",
            scope="e2e",
            dimension="intent",
        ),
        TaskName.E2E_EFFECT: TaskSpec(
            name=TaskName.E2E_EFFECT,
            artifact_stem="e2e_effect",
            scope="e2e",
            dimension="effect",
        ),
        TaskName.LOCAL_INTENT: TaskSpec(
            name=TaskName.LOCAL_INTENT,
            artifact_stem="local_intent",
            scope="local",
            dimension="intent",
        ),
        TaskName.LOCAL_EFFECT: TaskSpec(
            name=TaskName.LOCAL_EFFECT,
            artifact_stem="local_effect",
            scope="local",
            dimension="effect",
        ),
    }
)

MODE_TASKS: Mapping[EvaluationMode, tuple[TaskName, ...]] = MappingProxyType(
    {
        EvaluationMode.LITE: (
            TaskName.E2E_INTENT,
            TaskName.LOCAL_INTENT,
        ),
        EvaluationMode.FULL: (
            TaskName.E2E_INTENT,
            TaskName.E2E_EFFECT,
            TaskName.LOCAL_INTENT,
            TaskName.LOCAL_EFFECT,
        ),
    }
)


@dataclass(frozen=True)
class TaskSelection:
    """A validated mode preset or ordered explicit task selection."""

    tasks: tuple[TaskName, ...]
    mode: EvaluationMode | None = None

    @property
    def requires_effect_artifacts(self) -> bool:
        return any(TASK_SPECS[task].dimension == "effect" for task in self.tasks)

    @property
    def requires_patches(self) -> bool:
        return self.requires_effect_artifacts


def _parse_mode(mode: str | EvaluationMode) -> EvaluationMode:
    try:
        return EvaluationMode(mode)
    except ValueError as error:
        choices = ", ".join(item.value for item in EvaluationMode)
        raise ValueError(f"unknown evaluation mode {mode!r}; choose one of: {choices}") from error


def _parse_task(task: str | TaskName) -> TaskName:
    try:
        return TaskName(task)
    except ValueError as error:
        choices = ", ".join(item.value for item in TaskName)
        raise ValueError(f"unknown evaluation task {task!r}; choose one of: {choices}") from error


def resolve_task_selection(
    *,
    mode: str | EvaluationMode | None = None,
    tasks: Sequence[str | TaskName] | None = None,
) -> TaskSelection:
    """Resolve mutually exclusive mode and fine-grained task arguments."""

    explicit_tasks = tuple(tasks or ())
    if mode is not None and explicit_tasks:
        raise ValueError("--mode and --task are mutually exclusive")
    if mode is None and not explicit_tasks:
        raise ValueError("select one --mode or at least one --task")

    if mode is not None:
        parsed_mode = _parse_mode(mode)
        return TaskSelection(mode=parsed_mode, tasks=MODE_TASKS[parsed_mode])

    parsed_tasks = tuple(_parse_task(task) for task in explicit_tasks)
    duplicates = sorted(
        {task.value for task in parsed_tasks if parsed_tasks.count(task) > 1}
    )
    if duplicates:
        raise ValueError(f"duplicate task selection: {', '.join(duplicates)}")
    return TaskSelection(tasks=parsed_tasks)
