"""Concurrent generation and scoring over prepared evaluation tasks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from pydantic import BaseModel
from tqdm.auto import tqdm

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
    show_progress: bool = False,
    completed_instances: Mapping[
        TaskName, Mapping[str, InstanceRunResult]
    ] | None = None,
    prior_token_usage: Mapping[str, int] | None = None,
    on_instance_completed: Callable[
        [TaskName, str, InstanceRunResult, Mapping[str, int]], None
    ] | None = None,
    on_token_usage: Callable[[Mapping[str, int]], None] | None = None,
) -> EvaluationRunResult:
    """Generate and score all prepared tasks while retaining per-instance failures."""

    if workers < 1:
        raise ValueError("workers must be at least 1")
    submissions = {
        instance.instance_id: instance for instance in prepared.submission.instances
    }
    task_results: dict[TaskName, TaskRunResult] = {}
    resumed = completed_instances or {}
    base_token_usage = dict(prior_token_usage or {})

    def combined_token_usage() -> dict[str, int]:
        current = model.token_usage
        return {
            key: base_token_usage.get(key, 0) + current.get(key, 0)
            for key in base_token_usage.keys() | current.keys()
        }

    for task, prepared_task in prepared.tasks.items():
        evaluable_ids = set(prepared_task.evaluable_instance_ids)
        completed = dict(resumed.get(task, {}))
        unexpected_ids = sorted(set(completed) - evaluable_ids)
        if unexpected_ids:
            raise ValueError(
                f"resumed task {task.value} contains unexpected instances: "
                f"{unexpected_ids[:3]!r}"
            )
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
                if instance_id not in completed
            }
            completed_futures = as_completed(futures)
            progress_bar = None
            if show_progress:
                progress_bar = tqdm(
                    completed_futures,
                    total=len(prepared_task.evaluable_instance_ids),
                    initial=len(completed),
                    desc=f"Evaluating {task.value}",
                    unit="instance",
                )
                completed_futures = progress_bar
            for future in completed_futures:
                instance_id = futures[future]
                try:
                    instance_result = future.result()
                except Exception as error:
                    failures[instance_id] = f"{type(error).__name__}: {error}"
                    if on_token_usage is not None:
                        on_token_usage(combined_token_usage())
                else:
                    usage = combined_token_usage()
                    if on_instance_completed is not None:
                        on_instance_completed(
                            task,
                            instance_id,
                            instance_result,
                            usage,
                        )
                    completed[instance_id] = instance_result
                if progress_bar is not None:
                    progress_bar.set_postfix(
                        completed=len(completed),
                        failed=len(failures),
                        tokens=combined_token_usage().get("total_tokens", 0),
                    )
            if progress_bar is not None:
                progress_bar.close()

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
        token_usage=combined_token_usage(),
    )
