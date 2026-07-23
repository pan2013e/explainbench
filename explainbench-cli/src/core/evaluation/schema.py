"""Legacy import path for canonical evaluator prediction schemas."""

from explainbench.evaluation.predictions import (
    AnswerPrediction,
    E2EEffectPrediction,
)

MCQ = AnswerPrediction

__all__ = ["AnswerPrediction", "E2EEffectPrediction", "MCQ"]
