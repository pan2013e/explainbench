"""Shared multiple-choice formatting, normalization, and scoring."""

from __future__ import annotations

from string import ascii_lowercase
from typing import Any, Sequence


def normalize_choice(value: Any) -> Any:
    """Normalize one answer label while leaving invalid types for schema validation."""

    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    if normalized not in ascii_lowercase:
        raise ValueError("must be a single ASCII letter")
    return normalized


def format_choices(choices: Sequence[str], formatter: str = "{})") -> str:
    """Label up to 26 choices with lowercase ASCII letters."""

    if len(choices) > len(ascii_lowercase):
        raise ValueError("cannot format more than 26 choices")
    return "\n".join(
        f"{formatter.format(ascii_lowercase[index])} {choice}"
        for index, choice in enumerate(choices)
    )


def mcq_score(prediction: Sequence[str], ground_truth: Sequence[str]) -> float:
    """Score a selection with the ExplainBench subset-credit rule."""

    if not ground_truth:
        raise ValueError("ground truth must contain at least one answer")
    prediction_set = set(prediction)
    ground_truth_set = set(ground_truth)
    if prediction_set - ground_truth_set:
        return 0.0
    return len(prediction_set & ground_truth_set) / len(ground_truth_set)
