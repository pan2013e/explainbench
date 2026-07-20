"""High-level ExplainBench evaluation API."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from explainbench.evaluation.inference import Model
from explainbench.evaluation.preparation import prepare_evaluation
from explainbench.evaluation.registry import EvaluationMode, TaskName, resolve_task_selection
from explainbench.evaluation.results import EvaluationResult, build_evaluation_result
from explainbench.evaluation.runner import InferenceModel, run_evaluation
from explainbench.schemas import Submission


DEFAULT_EVALUATOR_MODEL = "gpt-5-mini-2025-08-07"


def evaluate_submission(
    submission: Submission,
    *,
    mode: str | EvaluationMode | None = None,
    tasks: Sequence[str | TaskName] | None = None,
    model_id: str = DEFAULT_EVALUATOR_MODEL,
    num_generations: int = 5,
    workers: int = 10,
    artifacts_dir: str | Path | None = None,
    inference_model: InferenceModel | None = None,
) -> EvaluationResult:
    """Prepare, run, score, and serialize one submission evaluation."""

    if not model_id.strip():
        raise ValueError("model_id must be a nonempty string")
    if num_generations < 1:
        raise ValueError("num_generations must be at least 1")
    if workers < 1:
        raise ValueError("workers must be at least 1")

    selection = resolve_task_selection(mode=mode, tasks=tasks)
    prepared = prepare_evaluation(
        submission,
        selection,
        artifacts_dir=artifacts_dir,
    )

    evaluator = inference_model
    if evaluator is None:
        evaluator = Model(model_id, n=num_generations)
    run = run_evaluation(prepared, evaluator, workers=workers)
    return build_evaluation_result(
        prepared,
        run,
        model_id=model_id,
        num_generations=num_generations,
    )
