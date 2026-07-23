"""Shared loading and validation for ExplainBench submissions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Collection

from pydantic import ValidationError

from explainbench.schemas import Submission


class ValidationProfile(StrEnum):
    """Requirements imposed by a consumer of a submission."""

    BASE = "base"
    LITE = "lite"
    EFFECT = "effect"
    QUESTION_BUILDER_LOCAL = "question-builder-local"
    FULL = "full"

    @property
    def requires_patches(self) -> bool:
        return self in {self.EFFECT, self.QUESTION_BUILDER_LOCAL, self.FULL}


@dataclass(frozen=True)
class ValidationIssue:
    """One human-readable problem in a submission."""

    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}" if self.location else self.message


class SubmissionValidationError(ValueError):
    """Raised when a submission cannot be loaded or does not satisfy a profile."""

    def __init__(self, issues: Collection[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(str(issue) for issue in self.issues))


def _format_location(location: tuple[Any, ...]) -> str:
    result = ""
    for part in location:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += ("." if result else "") + str(part)
    return result


def _pydantic_issues(error: ValidationError) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for detail in error.errors(include_url=False, include_context=False):
        message = detail["msg"]
        if message.startswith("Value error, "):
            message = message.removeprefix("Value error, ")
        issues.append(
            ValidationIssue(
                location=_format_location(detail["loc"]),
                message=message,
            )
        )
    return issues


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON value {value!r} is not allowed")


def _reject_duplicate_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _decode_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SubmissionValidationError(
            [ValidationIssue("file", f"cannot read {path}: {error.strerror or error}")]
        ) from error
    except UnicodeError as error:
        raise SubmissionValidationError(
            [ValidationIssue("file", f"must be UTF-8 encoded: {error}")]
        ) from error

    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_fields,
            parse_constant=_reject_nonstandard_constant,
        )
    except json.JSONDecodeError as error:
        raise SubmissionValidationError(
            [
                ValidationIssue(
                    "JSON",
                    f"{error.msg} (line {error.lineno}, column {error.colno})",
                )
            ]
        ) from error
    except ValueError as error:
        raise SubmissionValidationError(
            [ValidationIssue("JSON", str(error))]
        ) from error


@lru_cache(maxsize=1)
def supported_instance_ids() -> frozenset[str]:
    """Return the instance IDs included in the current ExplainBench dataset."""

    resource = files("explainbench").joinpath("data/benchmark_instance_ids.json")
    values = json.loads(resource.read_text(encoding="utf-8"))
    return frozenset(values)


_DIFF_HEADER = re.compile(r"^diff --git a/\S+ b/\S+$", re.MULTILINE)
_OLD_FILE_HEADER = re.compile(r"^--- (?:a/\S+|/dev/null)(?:\t.*)?$", re.MULTILINE)
_NEW_FILE_HEADER = re.compile(r"^\+\+\+ (?:b/\S+|/dev/null)(?:\t.*)?$", re.MULTILINE)
_HUNK_HEADER = re.compile(
    r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$", re.MULTILINE
)


def is_basic_unified_diff(patch: str) -> bool:
    """Check for the structural markers of a git-style unified diff."""

    patch = patch.replace("\r\n", "\n")
    return all(
        pattern.search(patch)
        for pattern in (_DIFF_HEADER, _OLD_FILE_HEADER, _NEW_FILE_HEADER, _HUNK_HEADER)
    )


def validate_submission(
    submission: Submission,
    *,
    profile: ValidationProfile = ValidationProfile.BASE,
    benchmark_ids: Collection[str] | None = None,
) -> Submission:
    """Apply benchmark and consumer-specific validation to a parsed submission."""

    known_ids = supported_instance_ids() if benchmark_ids is None else benchmark_ids
    issues: list[ValidationIssue] = []

    for index, instance in enumerate(submission.instances):
        prefix = f"instances[{index}]"
        if instance.instance_id not in known_ids:
            issues.append(
                ValidationIssue(
                    f"{prefix}.instance_id",
                    f"unsupported ExplainBench instance {instance.instance_id!r}",
                )
            )

        patch = instance.model_patch
        if profile.requires_patches and (patch is None or not patch.strip()):
            issues.append(
                ValidationIssue(
                    f"{prefix}.model_patch",
                    f"a nonempty patch is required for the {profile.value} profile",
                )
            )
        elif patch is not None and patch.strip() and not is_basic_unified_diff(patch):
            issues.append(
                ValidationIssue(
                    f"{prefix}.model_patch",
                    "must be a git-style unified diff",
                )
            )

    if issues:
        raise SubmissionValidationError(issues)
    return submission


def load_submission(
    path: str | Path,
    *,
    profile: ValidationProfile = ValidationProfile.BASE,
    benchmark_ids: Collection[str] | None = None,
) -> Submission:
    """Read, parse, and validate a submission JSON document."""

    data = _decode_json(Path(path))
    try:
        submission = Submission.model_validate(data)
    except ValidationError as error:
        raise SubmissionValidationError(_pydantic_issues(error)) from error
    return validate_submission(
        submission,
        profile=profile,
        benchmark_ids=benchmark_ids,
    )
