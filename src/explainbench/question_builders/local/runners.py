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
TRACE_PROGRAM_STATE_MODULE = "execution.trace"
BUILD_STEP1_MODULE = "dataset.extract_ground_truths.effect.build_step1"


DIVERGENCE_REQUIRED_FIELDS = frozenset(
    {
        "file_path",
        "function_name",
        "buggy_event_type",
        "patched_event_type",
        "buggy_statement",
        "patched_statement",
        "before_or_after",
        "buggy_lineno",
        "patched_lineno",
        "diff",
        "buggy_variables",
        "patched_variables",
    }
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


def _tracing_run_id(context: StageContext) -> str:
    identity = f"{context.submission_id}\0{context.instance.instance_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"explainbench-trace-{digest}-attempt-{context.total_attempt}"


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


def _validate_trace_artifact_result(
    result: StoredStageResult,
    *,
    label: str,
) -> None:
    instance_id = result.data.get("instance_id")
    run_id = result.data.get("run_id")
    if not isinstance(instance_id, str) or not instance_id:
        raise ValueError(f"{label} result requires a nonempty instance_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"{label} result requires a nonempty run_id")
    manifest = ArtifactManifest.model_validate(
        result.data.get("artifact_manifest")
    )
    paths = {item.path for item in manifest.files}
    if not any(path.startswith("buggy_traces/") for path in paths):
        raise ValueError(f"{label} manifest requires buggy trace files")
    if not any(path.startswith("patched_traces/") for path in paths):
        raise ValueError(f"{label} manifest requires patched trace files")


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
        _validate_trace_artifact_result(result, label="tracking")


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


class TraceProgramStateRunner:
    """Invoke the canonical detailed state-tracing command."""

    def run_instance(self, context: StageContext) -> StageResult:
        select_result = context.upstream_results.get("select-trace-functions")
        if select_result is None:
            raise StageExecutionError(
                "trace-program-state requires select-trace-functions output",
                category="missing_upstream_result",
                retryable=False,
            )
        allowed_functions_path = (
            context.attempt_directory / "allowed_functions.json"
        )
        atomic_write_json(
            allowed_functions_path,
            {
                context.submission_id: {
                    context.instance.instance_id: select_result.data.get(
                        "functions"
                    ),
                }
            },
        )

        tracing_work_directory = context.attempt_directory / "tracing"
        report_directory = context.attempt_directory / "reports"
        run_id = _tracing_run_id(context)
        run_canonical_module(
            TRACE_PROGRAM_STATE_MODULE,
            (
                "--agent",
                context.submission_id,
                "--instance-ids",
                context.instance.instance_id,
                "--predictions-path",
                str(context.workspace / "input" / "predictions.json"),
                "--allowed-functions-path",
                str(allowed_functions_path),
                "--run-id",
                run_id,
                "--max-workers",
                "1",
                "--timeout",
                str(context.config.trace_test_timeout_seconds),
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
                str(tracing_work_directory),
            ),
            context,
            timeout=context.config.trace_command_timeout_seconds,
            retryable_nonzero=True,
        )

        tracing_root = (
            tracing_work_directory
            / "logs"
            / "run_evaluation"
            / run_id
            / context.submission_id.replace("/", "__")
            / context.instance.instance_id
        )
        _require_trace_files(tracing_root, "buggy_traces")
        _require_trace_files(tracing_root, "patched_traces")
        manifest = build_artifact_manifest(
            tracing_root,
            relative_to=context.work_directory.parent,
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
        _validate_trace_artifact_result(result, label="detailed tracing")


class FindFirstDivergenceRunner:
    """Invoke canonical step 1 to locate the first trace divergence."""

    def run_instance(self, context: StageContext) -> StageResult:
        trace_result = context.upstream_results.get("trace-program-state")
        if trace_result is None:
            raise StageExecutionError(
                "find-first-divergence requires trace-program-state output",
                category="missing_upstream_result",
                retryable=False,
            )

        trace_instance_directory = (
            context.workspace
            / "stages"
            / "trace-program-state"
            / "instances"
            / context.instance.instance_id
        )
        try:
            _, trace_root = resolve_artifact_root(
                trace_result.data.get("artifact_manifest"),
                relative_to=trace_instance_directory,
            )
        except (TypeError, ValueError) as error:
            raise StageExecutionError(
                f"detailed trace artifact manifest is invalid: {error}",
                category="canonical_output_invalid",
                retryable=False,
            ) from error
        if not trace_root.is_dir():
            raise StageExecutionError(
                f"detailed trace artifact root is missing: {trace_root}",
                category="canonical_output_missing",
                retryable=True,
            )

        output_path = context.attempt_directory / "step1.json"
        arguments = [
            "--agent",
            context.submission_id,
            "--instance-ids",
            context.instance.instance_id,
            "--trace-root-template",
            str(trace_root.parent),
            "--output-path",
            str(output_path),
            "--depth-threshold",
            str(context.config.divergence_depth_threshold),
            "--timeout",
            str(context.config.divergence_timeout_seconds),
            "--instance-workers",
            str(context.config.divergence_instance_workers),
            "--agent-workers",
            str(context.config.divergence_agent_workers),
            "--variable-max-depth",
            str(context.config.divergence_variable_max_depth),
            "--parameter-max-depth",
            str(context.config.divergence_parameter_max_depth),
            "--simplify"
            if context.config.divergence_simplify
            else "--no-simplify",
        ]
        run_canonical_module(
            BUILD_STEP1_MODULE,
            arguments,
            context,
            timeout=context.config.divergence_command_timeout_seconds,
            retryable_nonzero=True,
        )

        payload = _read_json(output_path)
        if not isinstance(payload, dict):
            raise StageExecutionError(
                "divergence output must be a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )
        agent_results = payload.get(context.submission_id)
        if not isinstance(agent_results, dict):
            raise StageExecutionError(
                "divergence output does not contain the submission ID",
                category="canonical_output_missing",
                retryable=True,
            )
        if context.instance.instance_id not in agent_results:
            raise StageExecutionError(
                "divergence output does not contain the instance ID",
                category="canonical_output_missing",
                retryable=True,
            )
        divergence = agent_results[context.instance.instance_id]
        if divergence is None:
            raise StageExecutionError(
                "canonical divergence computation returned null",
                category="canonical_output_invalid",
                retryable=True,
            )
        if not isinstance(divergence, dict):
            raise StageExecutionError(
                "divergence result must be an object or an empty object",
                category="canonical_output_invalid",
                retryable=False,
            )

        result_data = {
            "instance_id": context.instance.instance_id,
            "divergence": divergence,
        }
        if not divergence:
            result_data["fallback_reason"] = "no_usable_agent_divergence"
        result = StageResult.completed(result_data)
        self.validate_result(result.to_stored())
        return result

    def validate_result(self, result: StoredStageResult) -> None:
        instance_id = result.data.get("instance_id")
        divergence = result.data.get("divergence")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError(
                "divergence result requires a nonempty instance_id"
            )
        if not isinstance(divergence, dict):
            raise ValueError("divergence result must be an object")
        if not divergence:
            if result.data.get("fallback_reason") != (
                "no_usable_agent_divergence"
            ):
                raise ValueError(
                    "empty divergence result requires an explicit fallback"
                )
            return
        missing = sorted(DIVERGENCE_REQUIRED_FIELDS - divergence.keys())
        if missing:
            raise ValueError(
                "divergence result is missing required fields: "
                + ", ".join(missing)
            )
