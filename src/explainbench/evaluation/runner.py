"""Concurrent generation and scoring over prepared evaluation tasks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Mapping, Protocol

from pydantic import BaseModel

from explainbench.evaluation.predictions import Prediction
from explainbench.evaluation.preparation import PreparedEvaluation
from explainbench.evaluation.registry import TaskName
from explainbench.evaluation.scoring import score_prediction
from explainbench.evaluation.tasks import build_prompt, prediction_schema


class InferenceModel(Protocol):
    token_usage: Mapping[str, int]

    def infer(
        self,
        messages: str | list[dict[str, str]],
        schema: type[BaseModel],
    ) -> list[BaseModel]: ...


@dataclass(frozen=True)
class InstanceRunResult:
    predictions: tuple[Prediction, ...]
    scores: tuple[float, ...]


@dataclass(frozen=True)
class TaskRunResult:
    task: TaskName
    instances: Mapping[str, InstanceRunResult]
    skipped_instance_ids: tuple[str, ...]
    failures: Mapping[str, str]


@dataclass(frozen=True)
class EvaluationRunResult:
    tasks: Mapping[TaskName, TaskRunResult]
    token_usage: Mapping[str, int]


def _run_instance(
    *,
    task: TaskName,
    explanation: str,
    context,
    ground_truth,
    model: InferenceModel,
) -> InstanceRunResult:
    prompt = build_prompt(task, explanation, context)
    schema = prediction_schema(task)
    raw_predictions = model.infer(prompt, schema)
    if not raw_predictions:
        raise ValueError("model returned no generations")
    predictions: list[Prediction] = []
    scores: list[float] = []
    for prediction in raw_predictions:
        if not isinstance(prediction, schema):
            raise TypeError(
                f"model returned {type(prediction).__name__}; expected {schema.__name__}"
            )
        predictions.append(prediction)
        scores.append(score_prediction(task, prediction, ground_truth))
    return InstanceRunResult(
        predictions=tuple(predictions),
        scores=tuple(scores),
    )


def run_evaluation(
    prepared: PreparedEvaluation,
    model: InferenceModel,
    *,
    workers: int = 10,
) -> EvaluationRunResult:
    """Generate and score all prepared tasks while retaining per-instance failures."""

    if workers < 1:
        raise ValueError("workers must be at least 1")
    submissions = {
        instance.instance_id: instance for instance in prepared.submission.instances
    }
    task_results: dict[TaskName, TaskRunResult] = {}

    for task, prepared_task in prepared.tasks.items():
        completed: dict[str, InstanceRunResult] = {}
        failures: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _run_instance,
                    task=task,
                    explanation=submissions[instance_id].explanation,
                    context=prepared_task.artifacts.context[instance_id],
                    ground_truth=prepared_task.artifacts.ground_truths[instance_id],
                    model=model,
                ): instance_id
                for instance_id in prepared_task.evaluable_instance_ids
            }
            for future in as_completed(futures):
                instance_id = futures[future]
                try:
                    completed[instance_id] = future.result()
                except Exception as error:
                    failures[instance_id] = f"{type(error).__name__}: {error}"

        ordered_instances = {
            instance_id: completed[instance_id]
            for instance_id in prepared_task.evaluable_instance_ids
            if instance_id in completed
        }
        ordered_failures = {
            instance_id: failures[instance_id]
            for instance_id in prepared_task.evaluable_instance_ids
            if instance_id in failures
        }
        task_results[task] = TaskRunResult(
            task=task,
            instances=ordered_instances,
            skipped_instance_ids=prepared_task.missing_instance_ids,
            failures=ordered_failures,
        )

    return EvaluationRunResult(
        tasks=task_results,
        token_usage=dict(model.token_usage),
    )
