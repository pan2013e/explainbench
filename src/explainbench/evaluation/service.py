"""High-level ExplainBench evaluation API."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from explainbench.evaluation.config import (
    DEFAULT_EVALUATOR_MODEL,
    DEFAULT_GENERATION_WORKERS,
    DEFAULT_INSTANCE_WORKERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_NUM_GENERATIONS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    EvaluatorSettings,
)
from explainbench.evaluation.inference import Model
from explainbench.evaluation.preparation import prepare_evaluation
from explainbench.evaluation.registry import (
    EvaluationMode,
    TaskName,
    resolve_task_selection,
)
from explainbench.evaluation.results import EvaluationResult, build_evaluation_result
from explainbench.evaluation.runner import InferenceModel, run_evaluation
from explainbench.schemas import Submission


def evaluate_submission(
    submission: Submission,
    *,
    mode: str | EvaluationMode | None = None,
    tasks: Sequence[str | TaskName] | None = None,
    model_id: str = DEFAULT_EVALUATOR_MODEL,
    num_generations: int = DEFAULT_NUM_GENERATIONS,
    workers: int = DEFAULT_INSTANCE_WORKERS,
    generation_workers: int = DEFAULT_GENERATION_WORKERS,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    artifacts_dir: str | Path | None = None,
    env_file: str | Path | None = None,
    inference_model: InferenceModel | None = None,
    show_progress: bool = False,
) -> EvaluationResult:
    """Prepare, run, score, and serialize one submission evaluation."""

    if not model_id.strip():
        raise ValueError("model_id must be a nonempty string")
    if num_generations < 1:
        raise ValueError("num_generations must be at least 1")
    if workers < 1:
        raise ValueError("workers must be at least 1")
    settings = EvaluatorSettings(
        model=model_id,
        num_generations=num_generations,
        instance_workers=workers,
        generation_workers=generation_workers,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        max_retries=max_retries,
    )

    selection = resolve_task_selection(mode=mode, tasks=tasks)
    prepared = prepare_evaluation(
        submission,
        selection,
        artifacts_dir=artifacts_dir,
    )

    evaluator = inference_model
    if evaluator is None:
        evaluator = Model(
            model_id,
            env_file=env_file,
            max_retries=max_retries,
            generation_workers=generation_workers,
            n=num_generations,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
    run = run_evaluation(
        prepared,
        evaluator,
        workers=workers,
        show_progress=show_progress,
    )
    return build_evaluation_result(
        prepared,
        run,
        settings=settings,
    )
