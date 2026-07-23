"""Submission checker used by the CLI and future Python APIs."""

from dataclasses import dataclass
from pathlib import Path

from explainbench.submission import ValidationProfile, load_submission


@dataclass(frozen=True)
class CheckSummary:
    submission_id: str
    instance_count: int
    explanation_count: int
    patch_count: int


def check_submission(path: str | Path) -> CheckSummary:
    """Validate a submission using the base/lite requirements."""

    submission = load_submission(path, profile=ValidationProfile.BASE)
    return CheckSummary(
        submission_id=submission.submission_id,
        instance_count=len(submission.instances),
        explanation_count=len(submission.instances),
        patch_count=sum(
            instance.model_patch is not None and bool(instance.model_patch.strip())
            for instance in submission.instances
        ),
    )
