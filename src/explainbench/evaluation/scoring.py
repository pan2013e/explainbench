"""Canonical task-specific ExplainBench scoring."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import ValidationError

from explainbench.evaluation.choices import mcq_score
from explainbench.evaluation.predictions import (
    AnswerPrediction,
    E2EEffectPrediction,
    Prediction,
)
from explainbench.evaluation.registry import TaskName
from explainbench.evaluation.schemas import (
    AnswerGroundTruth,
    E2EEffectGroundTruth,
    GroundTruthArtifact,
)


def validate_ground_truth(
    task: str | TaskName,
    value: GroundTruthArtifact | Mapping[str, Any],
) -> GroundTruthArtifact:
    """Validate a raw legacy ground truth with the schema for its task."""

    parsed_task = TaskName(task)
    schema = (
        E2EEffectGroundTruth
        if parsed_task is TaskName.E2E_EFFECT
        else AnswerGroundTruth
    )
    if isinstance(value, schema):
        return value
    try:
        return schema.model_validate(value)
    except ValidationError as error:
        raise ValueError(f"invalid ground truth for {parsed_task.value}: {error}") from error


def score_prediction(
    task: str | TaskName,
    prediction: Prediction,
    ground_truth: GroundTruthArtifact,
) -> float:
    """Score one structured prediction against normalized ground truth."""

    parsed_task = TaskName(task)
    if parsed_task is TaskName.E2E_EFFECT:
        if not isinstance(prediction, E2EEffectPrediction) or not isinstance(
            ground_truth, E2EEffectGroundTruth
        ):
            raise TypeError("e2e.effect requires before/after prediction and ground truth")
        return float(
            prediction.before_selection == ground_truth.before_answer
            and prediction.after_selection == ground_truth.after_answer
        )

    if not isinstance(prediction, AnswerPrediction) or not isinstance(
        ground_truth, AnswerGroundTruth
    ):
        raise TypeError(f"{parsed_task.value} requires answer-list prediction and ground truth")
    return mcq_score(prediction.answer, ground_truth.answer)
