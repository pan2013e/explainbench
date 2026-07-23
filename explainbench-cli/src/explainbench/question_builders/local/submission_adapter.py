"""Convert an ExplainBench submission to canonical SWE-bench predictions."""

from __future__ import annotations

from pathlib import Path

from explainbench.question_builders.common.atomic_files import atomic_write_json
from explainbench.schemas import Submission


class SubmissionAdapterError(ValueError):
    """Raised when a submission cannot produce canonical predictions."""


def build_predictions_payload(submission: Submission) -> dict[str, dict[str, str]]:
    """Return the prediction mapping expected by the canonical stage CLIs."""

    predictions: dict[str, dict[str, str]] = {}
    for instance in submission.instances:
        if instance.model_patch is None or not instance.model_patch.strip():
            raise SubmissionAdapterError(
                f"instance {instance.instance_id!r} does not contain a patch"
            )
        predictions[instance.instance_id] = {
            "instance_id": instance.instance_id,
            "model_patch": instance.model_patch,
            "model_name_or_path": submission.submission_id,
        }
    return predictions


def write_predictions_file(
    workspace: str | Path,
    submission: Submission,
) -> Path:
    """Atomically write the canonical prediction snapshot in the workspace."""

    destination = Path(workspace) / "input" / "predictions.json"
    atomic_write_json(destination, build_predictions_payload(submission))
    return destination
