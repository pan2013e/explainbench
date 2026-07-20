"""Versioned JSON result documents for ExplainBench evaluation."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Literal, Mapping

from pydantic import Field

from explainbench.evaluation.config import EvaluatorSettings
from explainbench.evaluation.predictions import Prediction
from explainbench.evaluation.preparation import PreparedEvaluation
from explainbench.evaluation.registry import EvaluationMode, TaskName
from explainbench.evaluation.runner import EvaluationRunResult, InstanceRunResult
from explainbench.schemas import StrictModel


class EvaluationSelectionResult(StrictModel):
    mode: EvaluationMode | None
    tasks: list[TaskName]


class EvaluatorResult(StrictModel):
    model: str
    num_generations: int = Field(ge=1)
    instance_workers: int = Field(ge=1)
    generation_workers: int = Field(ge=1)
    temperature: float = Field(ge=0)
    top_p: float = Field(gt=0, le=1)
    max_tokens: int = Field(ge=1)
    max_retries: int = Field(ge=1)
    token_usage: dict[str, int]


class TaskStatistics(StrictModel):
    mean: float | None
    sem: float | None


class TaskCounts(StrictModel):
    submitted: int = Field(ge=0)
    evaluated: int = Field(ge=0)
    skipped: int = Field(ge=0)
    failed: int = Field(ge=0)


class InstanceEvaluationResult(StrictModel):
    predictions: list[Prediction]
    scores: list[float]


class TaskEvaluationResult(StrictModel):
    statistics: TaskStatistics
    counts: TaskCounts
    instances: dict[str, InstanceEvaluationResult]
    skipped_instance_ids: list[str]
    failures: dict[str, str]


class EvaluationResult(StrictModel):
    schema_version: Literal[1] = 1
    submission_id: str
    selection: EvaluationSelectionResult
    evaluator: EvaluatorResult
    tasks: dict[TaskName, TaskEvaluationResult]


def _statistics(
    instances: Mapping[str, InstanceRunResult],
) -> TaskStatistics:
    """Compute mean and SEM across per-instance mean generation scores."""

    instance_means = [
        statistics.fmean(instance.scores)
        for instance in instances.values()
        if instance.scores
    ]
    if not instance_means:
        return TaskStatistics(mean=None, sem=None)
    mean = statistics.fmean(instance_means)
    sem = (
        statistics.stdev(instance_means) / math.sqrt(len(instance_means))
        if len(instance_means) > 1
        else None
    )
    return TaskStatistics(mean=mean, sem=sem)


def build_evaluation_result(
    prepared: PreparedEvaluation,
    run: EvaluationRunResult,
    *,
    settings: EvaluatorSettings,
) -> EvaluationResult:
    """Convert a completed evaluation run into schema version 1."""

    task_results: dict[TaskName, TaskEvaluationResult] = {}
    submitted_count = len(prepared.submission.instances)
    for task in prepared.selection.tasks:
        result = run.tasks[task]
        instances = {
            instance_id: InstanceEvaluationResult(
                predictions=list(instance.predictions),
                scores=list(instance.scores),
            )
            for instance_id, instance in result.instances.items()
        }
        task_results[task] = TaskEvaluationResult(
            statistics=_statistics(result.instances),
            counts=TaskCounts(
                submitted=submitted_count,
                evaluated=len(result.instances),
                skipped=len(result.skipped_instance_ids),
                failed=len(result.failures),
            ),
            instances=instances,
            skipped_instance_ids=list(result.skipped_instance_ids),
            failures=dict(result.failures),
        )

    return EvaluationResult(
        submission_id=prepared.submission.submission_id,
        selection=EvaluationSelectionResult(
            mode=prepared.selection.mode,
            tasks=list(prepared.selection.tasks),
        ),
        evaluator=EvaluatorResult(
            **settings.model_dump(),
            token_usage=dict(run.token_usage),
        ),
        tasks=task_results,
    )


def write_evaluation_result(result: EvaluationResult, path: str | Path) -> Path:
    """Write a result document as readable, standards-compliant JSON."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        result.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    output_path.write_text(f"{payload}\n", encoding="utf-8")
    return output_path
