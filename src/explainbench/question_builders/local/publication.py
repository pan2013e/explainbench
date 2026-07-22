"""Atomic publication of completed local-effect evaluator artifacts."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from explainbench.evaluation.artifacts import load_task_artifacts
from explainbench.evaluation.registry import TaskName
from explainbench.question_builders.common.atomic_files import atomic_write_json
from explainbench.question_builders.common.fingerprints import (
    fingerprint_file,
    fingerprint_value,
)
from explainbench.question_builders.common.orchestration import (
    QuestionBuilderError,
)
from explainbench.question_builders.local.runners import (
    ExportQuestionArtifactsRunner,
)
from explainbench.question_builders.local.workspace import LocalBuilderWorkspace


def _absolute_lexical_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _publish_link(generation: Path, output: Path) -> None:
    """Atomically point the public output path at a complete generation."""

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not output.is_symlink():
        if not output.is_dir():
            raise QuestionBuilderError(
                f"artifact output exists and is not a directory: {output}"
            )
        if any(output.iterdir()):
            raise QuestionBuilderError(
                "artifact output is a nonempty directory that ExplainBench does "
                f"not manage: {output}"
            )
        output.rmdir()

    temporary = output.parent / f".{output.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.symlink_to(generation, target_is_directory=True)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def publish_local_effect_artifacts(
    workspace: LocalBuilderWorkspace,
    *,
    output: Path,
) -> Path:
    """Merge instance checkpoints and atomically publish one artifact pair."""

    contexts: dict[str, object] = {}
    ground_truths: dict[str, object] = {}
    validator = ExportQuestionArtifactsRunner()
    for instance_id in workspace.manifest.instance_ids:
        status = workspace.read_status("export-question-artifacts", instance_id)
        if status is None or status.state not in {"completed", "skipped"}:
            raise QuestionBuilderError(
                "cannot publish artifacts while export checkpoints are incomplete"
            )
        result = workspace.read_result("export-question-artifacts", instance_id)
        validator.validate_result(result)
        if result.outcome == "skipped":
            continue
        contexts[instance_id] = result.data["context"]
        ground_truths[instance_id] = result.data["ground_truth"]

    if not contexts:
        raise QuestionBuilderError(
            "no local-effect questions were available for artifact export"
        )

    fingerprint = fingerprint_value(
        {
            "submission_id": workspace.manifest.submission_id,
            "context": contexts,
            "ground_truths": ground_truths,
        }
    )
    generation = workspace.root / "published" / fingerprint
    filename = f"local_effect__{workspace.manifest.submission_id}.json"
    context_path = generation / "context" / filename
    ground_truth_path = generation / "ground_truths" / filename
    atomic_write_json(context_path, contexts)
    atomic_write_json(ground_truth_path, ground_truths)

    load_task_artifacts(
        TaskName.LOCAL_EFFECT,
        submission_id=workspace.manifest.submission_id,
        artifacts_dir=generation,
    )
    files = {
        f"context/{filename}": fingerprint_file(context_path),
        f"ground_truths/{filename}": fingerprint_file(ground_truth_path),
    }
    atomic_write_json(
        generation / "artifact-manifest.json",
        {
            "schema_version": 1,
            "artifact_fingerprint": fingerprint,
            "files": files,
        },
    )

    public_output = _absolute_lexical_path(output)
    _publish_link(generation.resolve(), public_output)
    workspace.record_artifact_publication(
        output=public_output,
        fingerprint=fingerprint,
        files=files,
    )
    return public_output
