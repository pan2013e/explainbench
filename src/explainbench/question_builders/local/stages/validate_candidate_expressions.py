"""Classify candidate expressions from buggy and patched inspection values."""

from __future__ import annotations

from itertools import zip_longest
from typing import Any, Mapping

from deepdiff import DeepDiff
from pydantic import Field

from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
    StageResult,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.schemas import StrictModel


class ExecutedExpressionsResult(StrictModel):
    """Inspection output expected from the future execution stage."""

    metadata: dict[str, Any]
    candidates: list[str]
    buggy_inspection: dict[str, Any] | None = None
    patched_inspection: dict[str, Any] | None = None
    is_fallback_to_gold: bool = False
    gold_valid_changed_expressions: list[str] = Field(default_factory=list)
    gold_valid_unchanged_expressions: list[str] = Field(default_factory=list)


class ValidatedExpressionsResult(StrictModel):
    """Candidate pools after checking their observed values."""

    metadata: dict[str, Any]
    valid_changed_expressions: list[str]
    valid_unchanged_expressions: list[str]
    is_fallback_to_gold: bool = False


def values_equal(first: Any, second: Any) -> bool:
    return DeepDiff(
        first,
        second,
        significant_digits=5,
        ignore_private_variables=False,
    ) == {}


def _is_expected_missing_value(exception: Any) -> bool:
    if not isinstance(exception, Mapping):
        return False
    return (
        exception.get("stage") == "evaluation"
        and exception.get("type") in {"AttributeError", "NameError"}
        and (
            exception.get("type") == "NameError"
            or "NoneType" in str(exception.get("message", ""))
        )
    )


def expression_value_changed(
    buggy_value: Any,
    buggy_exception: Any,
    patched_value: Any,
    patched_exception: Any,
) -> bool:
    """Apply the legacy value/exception rules to one expression."""

    if values_equal(buggy_value, patched_value):
        return False
    if (buggy_value is None) != (patched_value is None):
        missing_exception = (
            buggy_exception if buggy_value is None else patched_exception
        )
        return _is_expected_missing_value(missing_exception)
    return True


def _as_list(value: Any, length: int) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return [None] * length
    return [value] * length


def compute_expression_changes(
    patched: Mapping[str, Any],
    buggy: Mapping[str, Any],
) -> dict[str, bool]:
    """Return expression-to-change classifications from inspection payloads."""

    lengths = [
        len(value)
        for value in (
            patched.get("expr"),
            patched.get("value"),
            patched.get("exception"),
            buggy.get("expr"),
            buggy.get("value"),
            buggy.get("exception"),
        )
        if isinstance(value, list)
    ]
    if not lengths:
        raise ValueError("inspection payloads contain no expression lists")
    length = max(lengths)
    expressions = _as_list(patched.get("expr"), length)
    if all(expression is None for expression in expressions):
        expressions = _as_list(buggy.get("expr"), length)
    patched_values = _as_list(patched.get("value"), length)
    patched_exceptions = _as_list(patched.get("exception"), length)
    buggy_values = _as_list(buggy.get("value"), length)
    buggy_exceptions = _as_list(buggy.get("exception"), length)

    changes: dict[str, bool] = {}
    for expression, patched_value, patched_exception, buggy_value, buggy_exception in zip_longest(
        expressions,
        patched_values,
        patched_exceptions,
        buggy_values,
        buggy_exceptions,
        fillvalue=None,
    ):
        if not isinstance(expression, str) or not expression:
            raise ValueError("inspection payload contains an invalid expression")
        changes[expression] = expression_value_changed(
            buggy_value,
            buggy_exception,
            patched_value,
            patched_exception,
        )
    return changes


class ValidateCandidateExpressionsRunner:
    """Produce changed and unchanged candidate pools."""

    def run_instance(self, context: StageContext) -> StageResult:
        try:
            executed = ExecutedExpressionsResult.model_validate(
                context.upstream_results["execute-candidate-expressions"].data
            )
            if executed.is_fallback_to_gold:
                changed = executed.gold_valid_changed_expressions
                unchanged = executed.gold_valid_unchanged_expressions
            else:
                if (
                    executed.buggy_inspection is None
                    or executed.patched_inspection is None
                ):
                    raise ValueError("buggy and patched inspections are required")
                changes = compute_expression_changes(
                    executed.patched_inspection,
                    executed.buggy_inspection,
                )
                unexpected = sorted(set(changes) - set(executed.candidates))
                if unexpected:
                    raise ValueError(
                        "inspection returned unrequested expressions: "
                        + ", ".join(unexpected)
                    )
                changed = [
                    expression
                    for expression in executed.candidates
                    if changes.get(expression) is True
                ]
                unchanged = [
                    expression
                    for expression in executed.candidates
                    if changes.get(expression) is False
                ]
        except (KeyError, ValueError) as error:
            raise StageExecutionError(
                f"could not validate candidate expressions: {error}",
                category="expression_inspection_invalid",
                retryable=False,
            ) from error
        output = ValidatedExpressionsResult(
            metadata=executed.metadata,
            valid_changed_expressions=changed,
            valid_unchanged_expressions=unchanged,
            is_fallback_to_gold=executed.is_fallback_to_gold,
        )
        return StageResult.completed(output.model_dump(mode="json"))

    def validate_result(self, result: StoredStageResult) -> None:
        ValidatedExpressionsResult.model_validate(result.data)

