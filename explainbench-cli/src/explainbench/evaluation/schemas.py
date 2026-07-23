"""Typed schemas for evaluation context and ground-truth artifacts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from explainbench.evaluation.choices import normalize_choice
from explainbench.schemas import StrictModel


def _validate_nonempty_text(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a nonempty string")
    return value


class ChoicesContext(StrictModel):
    choices: list[str] = Field(min_length=2, max_length=26)

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, choices: list[str]) -> list[str]:
        if any(not choice.strip() for choice in choices):
            raise ValueError("choices must contain nonempty strings")
        return choices


class E2EIntentContext(ChoicesContext):
    masked_test: str

    @field_validator("masked_test")
    @classmethod
    def validate_masked_test(cls, value: str) -> str:
        return _validate_nonempty_text(value)


class E2EEffectContext(ChoicesContext):
    test_content: str

    @field_validator("test_content")
    @classmethod
    def validate_test_content(cls, value: str) -> str:
        return _validate_nonempty_text(value)


class LocalContext(ChoicesContext):
    function_code_before_patch: str
    function_parameters_before_patch: str
    line: str
    before_or_after: Literal["before", "after"]

    @field_validator(
        "function_code_before_patch",
        "function_parameters_before_patch",
        "line",
    )
    @classmethod
    def validate_context_text(cls, value: str) -> str:
        return _validate_nonempty_text(value)


class LocalIntentContext(LocalContext):
    pass


class LocalEffectContext(LocalContext):
    pass


class AnswerGroundTruth(StrictModel):
    answer: list[str] = Field(min_length=1)

    @field_validator("answer", mode="before")
    @classmethod
    def normalize_scalar_answer(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) else value

    @field_validator("answer")
    @classmethod
    def normalize_answers(cls, answers: list[str]) -> list[str]:
        normalized = [normalize_choice(answer) for answer in answers]
        if len(normalized) != len(set(normalized)):
            raise ValueError("answer must not contain duplicate choices")
        return normalized


class E2EEffectGroundTruth(StrictModel):
    before_answer: str
    after_answer: str

    @field_validator("before_answer", "after_answer", mode="before")
    @classmethod
    def normalize_answers(cls, value: Any) -> Any:
        return normalize_choice(value)


ContextArtifact = (
    E2EIntentContext | E2EEffectContext | LocalIntentContext | LocalEffectContext
)
GroundTruthArtifact = AnswerGroundTruth | E2EEffectGroundTruth
