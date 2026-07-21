"""Thin package runners for canonical local-effect stage commands."""

from __future__ import annotations

import hashlib
import json

from pathlib import Path

from explainbench.question_builders.common.artifacts import (
    ArtifactManifest,
    build_artifact_manifest,
    resolve_artifact_root,
)
from explainbench.question_builders.common.atomic_files import atomic_write_json
from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
    StageResult,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.question_builders.common.subprocess_runner import (
    run_canonical_module,
)


IDENTIFY_PATCHED_FUNCTIONS_MODULE = (
    "dataset.extract_ground_truths.effect."
    "trace_step1_generate_qualname_whitelist"
)
TRACK_TEST_CALLS_MODULE = "execution.track"
SELECT_TRACE_FUNCTIONS_MODULE = (
    "dataset.extract_ground_truths.effect."
    "trace_step2_generate_call_stack_whitelist"
)


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StageExecutionError(
            f"cannot read canonical stage output {path}: {error}",
            category="canonical_output_unreadable",
            retryable=True,
        ) from error


class IdentifyPatchedFunctionsRunner:
    """Invoke the canonical patched-function identification command."""

    def run_instance(self, context: StageContext) -> StageResult:
        output_path = context.attempt_directory / "allowed_qualnames.json"
        predictions_path = context.workspace / "input" / "predictions.json"
        repository_cache_root = (
            context.config.repository_cache
            or context.workspace / "repositories"
        )
        repository_cache = repository_cache_root / context.instance.instance_id
        run_canonical_module(
            IDENTIFY_PATCHED_FUNCTIONS_MODULE,
            (
                "--agent",
                context.submission_id,
                "--instance-ids",
                context.instance.instance_id,
                "--predictions-path",
                str(predictions_path),
                "--repos-root",
                str(repository_cache),
                "--dataset-name",
                context.config.dataset_name,
                "--repository-remote",
                context.config.repository_remote,
                "--output-path",
                str(output_path),
            ),
            context,
            timeout=context.config.identify_timeout_seconds,
            retryable_nonzero=True,
        )

        payload = _read_json(output_path)
        if not isinstance(payload, dict):
            raise StageExecutionError(
                "patched-function output must be a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )
        agent_results = payload.get(context.submission_id)
        if not isinstance(agent_results, dict):
            raise StageExecutionError(
                "patched-function output does not contain the submission ID",
                category="canonical_output_missing",
                retryable=True,
            )
        qualnames = agent_results.get(context.instance.instance_id)
        if qualnames is None:
            raise StageExecutionError(
                "patched-function output does not contain the instance ID",
                category="canonical_output_missing",
                retryable=True,
            )
        result = StageResult.completed(
            {
                "instance_id": context.instance.instance_id,
                "qualnames": qualnames,
            }
        )
        self.validate_result(result.to_stored())
        return result

    def validate_result(self, result: StoredStageResult) -> None:
        instance_id = result.data.get("instance_id")
        qualnames = result.data.get("qualnames")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("identify result requires a nonempty instance_id")
        if not isinstance(qualnames, list) or not all(
            isinstance(item, str) and item for item in qualnames
        ):
            raise ValueError("identify result qualnames must be nonempty strings")
        if qualnames != sorted(set(qualnames)):
            raise ValueError("identify result qualnames must be sorted and unique")


def _tracking_run_id(context: StageContext) -> str:
    identity = f"{context.submission_id}\0{context.instance.instance_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"explainbench-track-{digest}-attempt-{context.total_attempt}"


def _require_trace_files(root: Path, directory_name: str) -> None:
    directory = root / directory_name
    if not directory.is_dir():
        raise StageExecutionError(
            f"tracking output does not contain {directory_name}",
            category="canonical_output_missing",
            retryable=True,
        )
    if not any(path.is_file() for path in directory.rglob("*.jsonl")):
        raise StageExecutionError(
            f"tracking output does not contain JSONL files in {directory_name}",
            category="canonical_output_missing",
            retryable=True,
        )


class TrackTestCallsRunner:
    """Invoke the canonical lightweight SWE-bench tracking command."""

    def run_instance(self, context: StageContext) -> StageResult:
        identify_result = context.upstream_results.get(
            "identify-patched-functions"
        )
        if identify_result is None:
            raise StageExecutionError(
                "track-test-calls requires identify-patched-functions output",
                category="missing_upstream_result",
                retryable=False,
            )
        qualnames = identify_result.data.get("qualnames")
        allowed_qualnames_path = (
            context.attempt_directory / "allowed_qualnames.json"
        )
        atomic_write_json(
            allowed_qualnames_path,
            {
                context.submission_id: {
                    context.instance.instance_id: qualnames,
                }
            },
        )

        tracking_work_directory = context.attempt_directory / "tracking"
        report_directory = context.attempt_directory / "reports"
        run_id = _tracking_run_id(context)
        run_canonical_module(
            TRACK_TEST_CALLS_MODULE,
            (
                "--agent",
                context.submission_id,
                "--instance-ids",
                context.instance.instance_id,
                "--predictions-path",
                str(context.workspace / "input" / "predictions.json"),
                "--allowed-qualnames-path",
                str(allowed_qualnames_path),
                "--run-id",
                run_id,
                "--max-workers",
                "1",
                "--timeout",
                str(context.config.track_test_timeout_seconds),
                "--dataset-name",
                context.config.dataset_name,
                "--split",
                "test",
                "--no-force-rebuild",
                "--cache-level",
                "env",
                "--no-clean",
                "--open-file-limit",
                "4096",
                "--namespace",
                "swebench",
                "--no-rewrite-reports",
                "--no-modal",
                "--instance-image-tag",
                "latest",
                "--env-image-tag",
                "latest",
                "--report-dir",
                str(report_directory),
                "--work-dir",
                str(tracking_work_directory),
            ),
            context,
            timeout=context.config.track_command_timeout_seconds,
            retryable_nonzero=True,
        )

        tracking_root = (
            tracking_work_directory
            / "logs"
            / "run_evaluation"
            / run_id
            / context.submission_id.replace("/", "__")
            / context.instance.instance_id
        )
        _require_trace_files(tracking_root, "buggy_traces")
        _require_trace_files(tracking_root, "patched_traces")
        instance_directory = context.work_directory.parent
        manifest = build_artifact_manifest(
            tracking_root,
            relative_to=instance_directory,
        )
        result = StageResult.completed(
            {
                "instance_id": context.instance.instance_id,
                "run_id": run_id,
                "artifact_manifest": manifest.model_dump(mode="json"),
            }
        )
        self.validate_result(result.to_stored())
        return result

    def validate_result(self, result: StoredStageResult) -> None:
        instance_id = result.data.get("instance_id")
        run_id = result.data.get("run_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("tracking result requires a nonempty instance_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("tracking result requires a nonempty run_id")
        manifest = ArtifactManifest.model_validate(
            result.data.get("artifact_manifest")
        )
        paths = {item.path for item in manifest.files}
        if not any(path.startswith("buggy_traces/") for path in paths):
            raise ValueError("tracking manifest requires buggy trace files")
        if not any(path.startswith("patched_traces/") for path in paths):
            raise ValueError("tracking manifest requires patched trace files")


class SelectTraceFunctionsRunner:
    """Select detailed-trace functions from lightweight call-stack traces."""

    def run_instance(self, context: StageContext) -> StageResult:
        identify_result = context.upstream_results.get(
            "identify-patched-functions"
        )
        track_result = context.upstream_results.get("track-test-calls")
        if identify_result is None or track_result is None:
            raise StageExecutionError(
                "select-trace-functions requires identification and tracking output",
                category="missing_upstream_result",
                retryable=False,
            )

        targets_path = context.attempt_directory / "allowed_qualnames.json"
        atomic_write_json(
            targets_path,
            {
                context.submission_id: {
                    context.instance.instance_id: identify_result.data.get(
                        "qualnames"
                    ),
                }
            },
        )
        track_instance_directory = (
            context.workspace
            / "stages"
            / "track-test-calls"
            / "instances"
            / context.instance.instance_id
        )
        _, tracking_root = resolve_artifact_root(
            track_result.data.get("artifact_manifest"),
            relative_to=track_instance_directory,
        )
        if not tracking_root.is_dir():
            raise StageExecutionError(
                f"tracking artifact root is missing: {tracking_root}",
                category="canonical_output_missing",
                retryable=True,
            )

        output_path = context.attempt_directory / "allowed_functions.json"
        run_canonical_module(
            SELECT_TRACE_FUNCTIONS_MODULE,
            (
                "--agent",
                context.submission_id,
                "--instance-ids",
                context.instance.instance_id,
                "--root-path",
                str(tracking_root),
                "--targets-json",
                str(targets_path),
                "--output-path",
                str(output_path),
            ),
            context,
            timeout=context.config.select_trace_timeout_seconds,
            retryable_nonzero=True,
        )

        payload = _read_json(output_path)
        if not isinstance(payload, dict):
            raise StageExecutionError(
                "trace-function output must be a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )
        submission_results = payload.get(context.submission_id)
        if not isinstance(submission_results, dict):
            raise StageExecutionError(
                "trace-function output does not contain the submission ID",
                category="canonical_output_missing",
                retryable=True,
            )
        functions = submission_results.get(context.instance.instance_id)
        if functions is None:
            raise StageExecutionError(
                "trace-function output does not contain the instance ID",
                category="canonical_output_missing",
                retryable=True,
            )
        result = StageResult.completed(
            {
                "instance_id": context.instance.instance_id,
                "functions": functions,
            }
        )
        self.validate_result(result.to_stored())
        return result

    def validate_result(self, result: StoredStageResult) -> None:
        instance_id = result.data.get("instance_id")
        functions = result.data.get("functions")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError(
                "trace-function result requires a nonempty instance_id"
            )
        if not isinstance(functions, list) or not all(
            isinstance(item, str) and item for item in functions
        ):
            raise ValueError(
                "trace-function result functions must be nonempty strings"
            )
        if functions != sorted(set(functions)):
            raise ValueError(
                "trace-function result functions must be sorted and unique"
            )
