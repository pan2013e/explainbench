"""Build stable local-effect multiple-choice questions from candidate pools."""

from __future__ import annotations

import random
from typing import Any

from explainbench.question_builders.common.fingerprints import fingerprint_value
from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
    StageResult,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.question_builders.local.stages.validate_candidate_expressions import (
    ValidatedExpressionsResult,
)
from explainbench.schemas import StrictModel


NO_EFFECT_CHOICE = (
    "The patch has no effect and none of the above expressions change in value"
)
CANNOT_INFER_CHOICE = "Cannot be answered by the explanation alone"


class AnswerChoicesResult(StrictModel):
    """Question metadata plus selected choices and answer labels."""

    metadata: dict[str, Any]
    choices: list[str]
    answer: list[str]
    is_fallback_to_gold: bool = False


def levenshtein_distance(first: str, second: str) -> int:
    if first == second:
        return 0
    if not first:
        return len(second)
    if not second:
        return len(first)
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for row, first_character in enumerate(first, start=1):
        current = [row]
        for column, second_character in enumerate(second, start=1):
            current.append(
                min(
                    current[column - 1] + 1,
                    previous[column] + 1,
                    previous[column - 1]
                    + (first_character != second_character),
                )
            )
        previous = current
    return previous[-1]


def normalized_similarity(first: str, second: str) -> float:
    return 1.0 - (
        levenshtein_distance(first, second) / max(len(first), len(second), 1)
    )


def _maximum_similarity(item: str, pool: list[str]) -> float:
    if not pool:
        return 0.0
    return max(normalized_similarity(item, other) for other in pool)


def _average_similarity(item: str, pool: list[str]) -> float:
    if not pool:
        return 0.0
    return sum(normalized_similarity(item, other) for other in pool) / len(pool)


def select_hard_anchors(
    correct_pool: list[str],
    incorrect_pool: list[str],
    count: int,
) -> list[str]:
    scored = [
        (_average_similarity(item, incorrect_pool), item)
        for item in correct_pool
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:count]]


def select_distractors(
    incorrect_pool: list[str],
    anchors: list[str],
    count: int,
    mmr_weight: float,
) -> list[str]:
    selected: list[str] = []
    remaining = list(incorrect_pool)
    while remaining and len(selected) < count:
        best_index = max(
            range(len(remaining)),
            key=lambda index: (
                mmr_weight
                * _maximum_similarity(remaining[index], anchors)
                - (1.0 - mmr_weight)
                * _maximum_similarity(remaining[index], selected)
            ),
        )
        selected.append(remaining.pop(best_index))
    return selected


def build_choices(
    *,
    correct_pool: list[str],
    incorrect_pool: list[str],
    correct_count: int,
    incorrect_count: int,
    mmr_weight: float,
    randomizer: random.Random,
    fallback_to_gold: bool,
    add_no_effect_choice: bool = True,
    add_cannot_infer_choice: bool = True,
) -> tuple[list[str], list[str]]:
    """Select and shuffle choices without mutating either input pool."""

    effective_correct = list(correct_pool)
    effective_incorrect = list(incorrect_pool)
    if fallback_to_gold:
        effective_incorrect.extend(effective_correct)
        effective_correct = []
        incorrect_count += correct_count
        correct_count = 0

    selected_correct = select_hard_anchors(
        effective_correct,
        effective_incorrect,
        correct_count,
    )
    selected_incorrect = select_distractors(
        effective_incorrect,
        selected_correct,
        incorrect_count,
        mmr_weight,
    )
    if len(selected_correct) < correct_count:
        remaining = [
            item for item in effective_correct if item not in selected_correct
        ]
        selected_correct.extend(
            randomizer.sample(
                remaining,
                min(correct_count - len(selected_correct), len(remaining)),
            )
        )
    if len(selected_incorrect) < incorrect_count:
        remaining = [
            item for item in effective_incorrect if item not in selected_incorrect
        ]
        selected_incorrect.extend(
            randomizer.sample(
                remaining,
                min(incorrect_count - len(selected_incorrect), len(remaining)),
            )
        )

    tagged = [(item, True) for item in selected_correct]
    tagged.extend((item, False) for item in selected_incorrect)
    randomizer.shuffle(tagged)
    choices = [item for item, _ in tagged]
    correct_flags = [is_correct for _, is_correct in tagged]
    if add_no_effect_choice:
        choices.append(NO_EFFECT_CHOICE)
        correct_flags.append(not any(correct_flags))
    if add_cannot_infer_choice:
        choices.append(CANNOT_INFER_CHOICE)
        correct_flags.append(False)
    labels = "abcdefghijklmnopqrstuvwxyz"
    answer = [
        labels[index]
        for index, is_correct in enumerate(correct_flags)
        if is_correct
    ]
    return choices, answer


class BuildAnswerChoicesRunner:
    """Select choices independently and reproducibly for each instance."""

    def run_instance(self, context: StageContext) -> StageResult:
        try:
            validated = ValidatedExpressionsResult.model_validate(
                context.upstream_results[
                    "validate-candidate-expressions"
                ].data
            )
        except (KeyError, ValueError) as error:
            raise StageExecutionError(
                f"could not read validated candidate expressions: {error}",
                category="validated_expressions_invalid",
            ) from error

        required_correct = 0 if validated.is_fallback_to_gold else (
            context.config.correct_choices
        )
        required_incorrect = context.config.incorrect_choices + (
            context.config.correct_choices if validated.is_fallback_to_gold else 0
        )
        available_incorrect = len(validated.valid_unchanged_expressions) + (
            len(validated.valid_changed_expressions)
            if validated.is_fallback_to_gold
            else 0
        )
        if (
            len(validated.valid_changed_expressions) < required_correct
            or available_incorrect < required_incorrect
        ):
            return StageResult.skipped(
                "insufficient validated expression choices",
                {
                    "available_changed": len(
                        validated.valid_changed_expressions
                    ),
                    "available_unchanged": len(
                        validated.valid_unchanged_expressions
                    ),
                },
            )

        seed = int(
            fingerprint_value(
                {
                    "base_seed": context.config.random_seed,
                    "instance_id": context.instance.instance_id,
                }
            )[:16],
            16,
        )
        choices, answer = build_choices(
            correct_pool=validated.valid_changed_expressions,
            incorrect_pool=validated.valid_unchanged_expressions,
            correct_count=context.config.correct_choices,
            incorrect_count=context.config.incorrect_choices,
            mmr_weight=context.config.mmr_weight,
            randomizer=random.Random(seed),
            fallback_to_gold=validated.is_fallback_to_gold,
        )
        output = AnswerChoicesResult(
            metadata=validated.metadata,
            choices=choices,
            answer=answer,
            is_fallback_to_gold=validated.is_fallback_to_gold,
        )
        return StageResult.completed(output.model_dump(mode="json"))

    def validate_result(self, result: StoredStageResult) -> None:
        if result.outcome == "skipped":
            return
        AnswerChoicesResult.model_validate(result.data)
