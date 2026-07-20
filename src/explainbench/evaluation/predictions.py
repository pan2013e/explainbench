"""Structured evaluator-model response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from explainbench.evaluation.choices import normalize_choice
from explainbench.schemas import StrictModel


class AnswerPrediction(StrictModel):
    """One or more selected choices for intent and local-effect tasks."""

    answer: list[str] = Field(min_length=1)

    @field_validator("answer")
    @classmethod
    def normalize_answers(cls, answers: list[str]) -> list[str]:
        normalized = [normalize_choice(answer) for answer in answers]
        if len(normalized) != len(set(normalized)):
            raise ValueError("answer must not contain duplicate choices")
        return normalized


class E2EEffectPrediction(StrictModel):
    """Selected test behavior before and after applying a patch."""

    before_selection: str
    after_selection: str

    @field_validator("before_selection", "after_selection", mode="before")
    @classmethod
    def normalize_selections(cls, value: Any) -> Any:
        return normalize_choice(value)


Prediction = AnswerPrediction | E2EEffectPrediction
