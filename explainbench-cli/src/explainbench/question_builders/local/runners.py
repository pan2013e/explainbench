"""Thin package runners for canonical local-effect stage commands."""

from __future__ import annotations

import hashlib
import json
import re

from pathlib import Path

from pydantic import ValidationError

from explainbench.evaluation.schemas import AnswerGroundTruth, LocalEffectContext
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
BUILD_STEP2_MODULE = "dataset.extract_ground_truths.effect.build_step2"
BUILD_STEP3_MODULE = "dataset.extract_ground_truths.effect.build_step3"
BUILD_STEP4_MODULE = "dataset.extract_ground_truths.effect.build_step4"
BUILD_STEP5_MODULE = "dataset.extract_ground_truths.effect.build_step5"
PERSISTENCE_FAILURE_EXIT_CODE = 86

NONE_OF_THE_ABOVE_CHOICE = (
    "The patch has no effect and none of the above expressions change in value"
)
CANNOT_INFER_CHOICE = "Cannot be answered by the explanation alone"
SAFE_ARTIFACT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


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


CANDIDATE_REQUIRED_METADATA = frozenset(
    {
        "instance_id",
        "agent",
        "file_path",
        "function_name",
        "buggy_lineno",
        "patched_lineno",
        "buggy_line_count",
        "patched_line_count",
        "test_id",
        "before_or_after",
        "prompt_length_chars",
        "function_code_before_patch",
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


def _inspection_run_id(context: StageContext) -> str:
    identity = f"{context.submission_id}\0{context.instance.instance_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"explainbench-inspect-{digest}-attempt-{context.total_attempt}"


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


class GenerateCandidateExpressionsRunner:
    """Invoke canonical step 2 to generate model candidate expressions."""

    @staticmethod
    def _resume_audit_directories(context: StageContext) -> tuple[Path, ...]:
        directories = []
        for path in context.work_directory.glob("attempt-*/model-audit"):
            if path.parent == context.attempt_directory:
                continue
            try:
                attempt = int(path.parent.name.removeprefix("attempt-"))
            except ValueError:
                continue
            if attempt < context.total_attempt and path.is_dir():
                directories.append((attempt, path))
        return tuple(path for _, path in sorted(directories, reverse=True))

    def run_instance(self, context: StageContext) -> StageResult:
        divergence_result = context.upstream_results.get(
            "find-first-divergence"
        )
        if divergence_result is None:
            raise StageExecutionError(
                "generate-candidate-expressions requires divergence output",
                category="missing_upstream_result",
                retryable=False,
            )

        divergence = divergence_result.data.get("divergence")
        if not isinstance(divergence, dict):
            raise StageExecutionError(
                "divergence output is not a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )

        step1_path = context.attempt_directory / "step1.json"
        atomic_write_json(
            step1_path,
            {
                context.submission_id: {
                    context.instance.instance_id: divergence,
                }
            },
        )
        output_path = context.attempt_directory / "step2.json"
        audit_directory = context.attempt_directory / "model-audit"
        arguments = [
            "--agent",
            context.submission_id,
            "--instance-ids",
            context.instance.instance_id,
            "--step1-path",
            str(step1_path),
            "--output-path",
            str(output_path),
            "--predictions-path",
            str(context.workspace / "input" / "predictions.json"),
            "--changed-candidates",
            str(context.config.candidate_generation_changed_candidates),
            "--unchanged-candidates",
            str(context.config.candidate_generation_unchanged_candidates),
            "--instance-workers",
            str(context.config.candidate_generation_instance_workers),
            "--agent-workers",
            str(context.config.candidate_generation_agent_workers),
            "--model",
            context.config.candidate_generation_model,
            "--reasoning-effort",
            context.config.candidate_generation_reasoning_effort,
            "--max-retries",
            str(context.config.candidate_generation_model_retries),
            "--audit-dir",
            str(audit_directory),
            "--inference"
            if context.config.candidate_generation_inference
            else "--no-inference",
        ]
        for resume_directory in self._resume_audit_directories(context):
            arguments.extend(
                ["--resume-audit-dir", str(resume_directory)]
            )
        if context.config.candidate_generation_env_file is not None:
            arguments.extend(
                [
                    "--env-file",
                    str(context.config.candidate_generation_env_file),
                ]
            )

        command_timeout = (
            context.config.candidate_generation_command_timeout_seconds
        )
        try:
            run_canonical_module(
                BUILD_STEP2_MODULE,
                arguments,
                context,
                timeout=command_timeout,
                retryable_nonzero=True,
            )
        except StageExecutionError as error:
            command_record = _read_json(
                context.attempt_directory / "command.json"
            )
            if (
                isinstance(command_record, dict)
                and command_record.get("return_code")
                == PERSISTENCE_FAILURE_EXIT_CODE
            ):
                raise StageExecutionError(
                    "a paid model response could not be stored; "
                    "automatic retry is disabled",
                    category="paid_response_persistence_failed",
                    retryable=False,
                ) from error
            raise

        payload = _read_json(output_path)
        if not isinstance(payload, dict):
            raise StageExecutionError(
                "candidate output must be a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )
        agent_results = payload.get(context.submission_id)
        if not isinstance(agent_results, dict):
            raise StageExecutionError(
                "candidate output does not contain the submission ID",
                category="canonical_output_missing",
                retryable=True,
            )
        if context.instance.instance_id not in agent_results:
            raise StageExecutionError(
                "candidate output does not contain the instance ID",
                category="canonical_output_missing",
                retryable=True,
            )
        candidates = agent_results[context.instance.instance_id]
        if candidates is None:
            raise StageExecutionError(
                "canonical candidate generation returned null",
                category="canonical_output_invalid",
                retryable=True,
            )
        if not isinstance(candidates, dict):
            raise StageExecutionError(
                "candidate result must be a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )

        source_response = candidates.pop("_source_response", None)
        result_data = {
            "instance_id": context.instance.instance_id,
            "candidates": candidates,
            "inference": context.config.candidate_generation_inference,
        }
        if not audit_directory.is_dir():
            atomic_write_json(
                audit_directory / "manifest.json",
                {
                    "schema_version": 1,
                    "request": None,
                    "responses": [],
                    "selected_response": None,
                    "fallback_reason": "no_usable_agent_divergence",
                },
            )
        result_data["artifact_manifest"] = build_artifact_manifest(
            audit_directory,
            relative_to=context.work_directory.parent,
        ).model_dump(mode="json")
        if source_response is not None:
            result_data["source_response"] = source_response
        if not candidates:
            result_data["fallback_reason"] = "no_usable_agent_divergence"
        result = StageResult.completed(result_data)
        self.validate_result(result.to_stored())
        return result

    def validate_result(self, result: StoredStageResult) -> None:
        instance_id = result.data.get("instance_id")
        candidates = result.data.get("candidates")
        inference = result.data.get("inference")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError(
                "candidate result requires a nonempty instance_id"
            )
        if not isinstance(candidates, dict):
            raise ValueError("candidate result must be an object")
        if not isinstance(inference, bool):
            raise ValueError("candidate result inference must be a boolean")
        if not candidates:
            if result.data.get("fallback_reason") != (
                "no_usable_agent_divergence"
            ):
                raise ValueError(
                    "empty candidate result requires an explicit fallback"
                )
            return

        prompt_length = candidates.get("prompt_length_chars")
        if not isinstance(prompt_length, int) or isinstance(prompt_length, bool):
            raise ValueError(
                "candidate result prompt_length_chars must be an integer"
            )
        if prompt_length < 0:
            raise ValueError(
                "candidate result prompt_length_chars must be nonnegative"
            )
        if not inference:
            return

        source_response = result.data.get("source_response")
        if not isinstance(source_response, dict):
            raise StageExecutionError(
                "candidate result does not identify its source response",
                category="canonical_output_invalid",
                retryable=True,
            )
        response_path = source_response.get("path")
        response_size = source_response.get("size")
        response_checksum = source_response.get("sha256")
        if (
            not isinstance(response_path, str)
            or not response_path
            or not isinstance(response_size, int)
            or isinstance(response_size, bool)
            or response_size < 0
            or not isinstance(response_checksum, str)
            or not re.fullmatch(r"[0-9a-f]{64}", response_checksum)
        ):
            raise StageExecutionError(
                "candidate source response record is invalid",
                category="canonical_output_invalid",
                retryable=True,
            )
        try:
            manifest = ArtifactManifest.model_validate(
                result.data.get("artifact_manifest")
            )
        except ValidationError as error:
            raise StageExecutionError(
                f"candidate audit artifact manifest is invalid: {error}",
                category="canonical_output_invalid",
                retryable=True,
            ) from error
        manifest_files = {item.path: item for item in manifest.files}
        response_file = manifest_files.get(response_path)
        if (
            response_file is None
            or response_file.size != response_size
            or response_file.sha256 != response_checksum
        ):
            raise StageExecutionError(
                "candidate source response does not match its artifact manifest",
                category="canonical_output_invalid",
                retryable=True,
            )

        missing = sorted(CANDIDATE_REQUIRED_METADATA - candidates.keys())
        if missing:
            raise StageExecutionError(
                "candidate generation did not produce complete metadata: "
                + ", ".join(missing),
                category="canonical_output_invalid",
                retryable=True,
            )
        for key in ("changed_candidates", "unchanged_candidates"):
            values = candidates.get(key)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise StageExecutionError(
                    f"candidate result {key} must be a list of nonempty strings",
                    category="canonical_output_invalid",
                    retryable=True,
                )
        for key in (
            "instance_id",
            "agent",
            "file_path",
            "function_name",
            "before_or_after",
            "function_code_before_patch",
        ):
            if not isinstance(candidates.get(key), str) or not candidates[key]:
                raise StageExecutionError(
                    f"candidate result {key} must be a nonempty string",
                    category="canonical_output_invalid",
                    retryable=True,
                )
        for key in (
            "buggy_lineno",
            "patched_lineno",
            "buggy_line_count",
            "patched_line_count",
            "test_id",
        ):
            value = candidates.get(key)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise StageExecutionError(
                    f"candidate result {key} must be a nonnegative integer",
                    category="canonical_output_invalid",
                    retryable=True,
                )


class ExecuteCandidateExpressionsRunner:
    """Invoke canonical step 3 execution and retain inspection artifacts."""

    def run_instance(self, context: StageContext) -> StageResult:
        candidate_result = context.upstream_results.get(
            "generate-candidate-expressions"
        )
        if candidate_result is None:
            raise StageExecutionError(
                "execute-candidate-expressions requires candidate output",
                category="missing_upstream_result",
                retryable=False,
            )

        candidates = candidate_result.data.get("candidates")
        if not isinstance(candidates, dict):
            raise StageExecutionError(
                "candidate output is not a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )
        changed = candidates.get("changed_candidates")
        unchanged = candidates.get("unchanged_candidates")
        if not isinstance(changed, list) or not isinstance(unchanged, list):
            skip_reason = (
                "no_candidate_expressions"
                if not candidates
                else "candidate_inference_disabled"
            )
            result = StageResult.skipped(
                skip_reason,
                {
                    "instance_id": context.instance.instance_id,
                    "candidate_count": 0,
                },
            )
            self.validate_result(result.to_stored())
            return result
        candidate_count = len(changed) + len(unchanged)
        if candidate_count == 0:
            result = StageResult.skipped(
                "no_candidate_expressions",
                {
                    "instance_id": context.instance.instance_id,
                    "candidate_count": 0,
                },
            )
            self.validate_result(result.to_stored())
            return result

        step2_path = context.attempt_directory / "step2.json"
        atomic_write_json(
            step2_path,
            {
                context.submission_id: {
                    context.instance.instance_id: candidates,
                }
            },
        )
        gold_step2_path = context.attempt_directory / "step2.gold.json"
        atomic_write_json(gold_step2_path, {"gold": {}})

        inspection_work_directory = (
            context.attempt_directory / "inspection"
        )
        report_directory = context.attempt_directory / "reports"
        output_path = context.attempt_directory / "step3.json"
        gold_output_path = context.attempt_directory / "step3.gold.json"
        run_id = _inspection_run_id(context)
        arguments = [
            "--execute",
            "--agent",
            context.submission_id,
            "--instance-ids",
            context.instance.instance_id,
            "--step2-path",
            str(step2_path),
            "--gold-step2-path",
            str(gold_step2_path),
            "--output-path",
            str(output_path),
            "--gold-output-path",
            str(gold_output_path),
            "--predictions-path",
            str(context.workspace / "input" / "predictions.json"),
            "--inspection-run-id-template",
            run_id,
            "--logs-root",
            str(inspection_work_directory),
            "--expression-set-id",
            str(context.config.expression_set_id),
            "--instance-workers",
            str(context.config.inspection_instance_workers),
            "--agent-workers",
            str(context.config.inspection_agent_workers),
            "--inspection-timeout",
            str(context.config.inspection_timeout_seconds),
            "--inspection-dataset-name",
            context.config.dataset_name,
            "--inspection-split",
            context.config.inspection_split,
            "--inspection-namespace",
            context.config.inspection_namespace,
            "--inspection-max-workers",
            str(context.config.inspection_max_workers),
            "--inspection-cache-level",
            context.config.inspection_cache_level,
            "--inspection-open-file-limit",
            str(context.config.inspection_open_file_limit),
            "--inspection-instance-image-tag",
            context.config.inspection_instance_image_tag,
            "--inspection-env-image-tag",
            context.config.inspection_env_image_tag,
            "--inspection-report-dir",
            str(report_directory),
            "--inspection-work-dir",
            str(inspection_work_directory),
            "--inspection-force-rebuild"
            if context.config.inspection_force_rebuild
            else "--no-inspection-force-rebuild",
            "--inspection-clean"
            if context.config.inspection_clean
            else "--no-inspection-clean",
            "--inspection-rewrite-reports"
            if context.config.inspection_rewrite_reports
            else "--no-inspection-rewrite-reports",
            "--inspection-modal"
            if context.config.inspection_modal
            else "--no-inspection-modal",
            "--no-process-gold",
        ]
        run_canonical_module(
            BUILD_STEP3_MODULE,
            arguments,
            context,
            timeout=context.config.inspection_command_timeout_seconds,
            retryable_nonzero=True,
        )

        inspection_root = (
            inspection_work_directory
            / "logs"
            / "run_evaluation"
            / run_id
            / context.submission_id
            / context.instance.instance_id
        )
        _require_trace_files(inspection_root, "buggy_traces")
        _require_trace_files(inspection_root, "patched_traces")
        manifest = build_artifact_manifest(
            inspection_root,
            relative_to=context.work_directory.parent,
        )
        result = StageResult.completed(
            {
                "instance_id": context.instance.instance_id,
                "candidate_count": candidate_count,
                "run_id": run_id,
                "artifact_manifest": manifest.model_dump(mode="json"),
            }
        )
        self.validate_result(result.to_stored())
        return result

    def validate_result(self, result: StoredStageResult) -> None:
        instance_id = result.data.get("instance_id")
        candidate_count = result.data.get("candidate_count")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError(
                "expression execution result requires a nonempty instance_id"
            )
        if (
            not isinstance(candidate_count, int)
            or isinstance(candidate_count, bool)
            or candidate_count < 0
        ):
            raise ValueError(
                "expression execution candidate_count must be nonnegative"
            )
        if result.outcome == "skipped":
            if candidate_count != 0:
                raise ValueError(
                    "skipped expression execution must have zero candidates"
                )
            if result.reason not in {
                "candidate_inference_disabled",
                "no_candidate_expressions",
            }:
                raise ValueError(
                    "expression execution has an unknown skip reason"
                )
            return
        if candidate_count == 0:
            raise ValueError(
                "completed expression execution requires candidates"
            )
        _validate_trace_artifact_result(result, label="expression inspection")


class ValidateCandidateExpressionsRunner:
    """Invoke canonical step 3 validation on saved inspection artifacts."""

    def run_instance(self, context: StageContext) -> StageResult:
        candidate_result = context.upstream_results.get(
            "generate-candidate-expressions"
        )
        execution_result = context.upstream_results.get(
            "execute-candidate-expressions"
        )
        if candidate_result is None or execution_result is None:
            raise StageExecutionError(
                "validate-candidate-expressions requires candidate and "
                "execution output",
                category="missing_upstream_result",
                retryable=False,
            )
        if execution_result.outcome == "skipped":
            result = StageResult.skipped(
                execution_result.reason or "no_candidate_expressions",
                {
                    "instance_id": context.instance.instance_id,
                    "candidate_count": execution_result.data.get(
                        "candidate_count", 0
                    ),
                },
            )
            self.validate_result(result.to_stored())
            return result

        candidates = candidate_result.data.get("candidates")
        if not isinstance(candidates, dict):
            raise StageExecutionError(
                "candidate output is not a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )
        run_id = execution_result.data.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise StageExecutionError(
                "expression execution output has no run ID",
                category="canonical_output_invalid",
                retryable=False,
            )

        execution_instance_directory = (
            context.workspace
            / "stages"
            / "execute-candidate-expressions"
            / "instances"
            / context.instance.instance_id
        )
        try:
            _, inspection_root = resolve_artifact_root(
                execution_result.data.get("artifact_manifest"),
                relative_to=execution_instance_directory,
            )
        except (TypeError, ValueError) as error:
            raise StageExecutionError(
                f"inspection artifact manifest is invalid: {error}",
                category="canonical_output_invalid",
                retryable=False,
            ) from error
        if not inspection_root.is_dir():
            raise StageExecutionError(
                f"inspection artifact root is missing: {inspection_root}",
                category="canonical_output_missing",
                retryable=True,
            )
        logs_root = inspection_root.parents[2]

        step2_path = context.attempt_directory / "step2.json"
        atomic_write_json(
            step2_path,
            {
                context.submission_id: {
                    context.instance.instance_id: candidates,
                }
            },
        )
        gold_step2_path = context.attempt_directory / "step2.gold.json"
        atomic_write_json(gold_step2_path, {"gold": {}})
        output_path = context.attempt_directory / "step3.json"
        gold_output_path = context.attempt_directory / "step3.gold.json"
        atomic_write_json(gold_output_path, {"gold": {}})

        run_canonical_module(
            BUILD_STEP3_MODULE,
            (
                "--validate",
                "--agent",
                context.submission_id,
                "--instance-ids",
                context.instance.instance_id,
                "--step2-path",
                str(step2_path),
                "--gold-step2-path",
                str(gold_step2_path),
                "--output-path",
                str(output_path),
                "--gold-output-path",
                str(gold_output_path),
                "--predictions-path",
                str(context.workspace / "input" / "predictions.json"),
                "--inspection-run-id-template",
                run_id,
                "--logs-root",
                str(logs_root),
                "--expression-set-id",
                str(context.config.expression_set_id),
                "--instance-workers",
                str(context.config.inspection_instance_workers),
                "--agent-workers",
                str(context.config.inspection_agent_workers),
                "--no-process-gold",
            ),
            context,
            timeout=context.config.inspection_command_timeout_seconds,
            retryable_nonzero=True,
        )

        payload = _read_json(output_path)
        if not isinstance(payload, dict):
            raise StageExecutionError(
                "validated candidate output must be a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )
        agent_results = payload.get(context.submission_id)
        if not isinstance(agent_results, dict):
            raise StageExecutionError(
                "validated candidate output lacks the submission ID",
                category="canonical_output_missing",
                retryable=True,
            )
        if context.instance.instance_id not in agent_results:
            raise StageExecutionError(
                "validated candidate output lacks the instance ID",
                category="canonical_output_missing",
                retryable=True,
            )
        validated = agent_results[context.instance.instance_id]
        if validated is None:
            raise StageExecutionError(
                "canonical candidate validation returned null",
                category="canonical_output_invalid",
                retryable=True,
            )
        if not isinstance(validated, dict):
            raise StageExecutionError(
                "validated candidate result must be a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )

        result = StageResult.completed(
            {
                "instance_id": context.instance.instance_id,
                "validated_candidates": validated,
            }
        )
        self.validate_result(result.to_stored())
        return result

    def validate_result(self, result: StoredStageResult) -> None:
        instance_id = result.data.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError(
                "candidate validation result requires a nonempty instance_id"
            )
        if result.outcome == "skipped":
            if result.reason not in {
                "candidate_inference_disabled",
                "no_candidate_expressions",
            }:
                raise ValueError("candidate validation has an unknown skip reason")
            if result.data.get("candidate_count") != 0:
                raise ValueError(
                    "skipped candidate validation must have zero candidates"
                )
            return

        validated = result.data.get("validated_candidates")
        if not isinstance(validated, dict):
            raise ValueError("validated candidate result must be an object")
        missing = sorted(CANDIDATE_REQUIRED_METADATA - validated.keys())
        if missing:
            raise ValueError(
                "validated candidate result is missing metadata: "
                + ", ".join(missing)
            )
        generated = []
        for key in ("changed_candidates", "unchanged_candidates"):
            values = validated.get(key)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise ValueError(
                    f"validated candidate {key} must contain strings"
                )
            generated.extend(values)
        classified = {}
        for key in (
            "valid_changed_expressions",
            "valid_unchanged_expressions",
        ):
            values = validated.get(key)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise ValueError(
                    f"validated candidate {key} must contain strings"
                )
            if len(values) != len(set(values)):
                raise ValueError(
                    f"validated candidate {key} must be unique"
                )
            classified[key] = values
        overlap = set(classified["valid_changed_expressions"]) & set(
            classified["valid_unchanged_expressions"]
        )
        if overlap:
            raise ValueError(
                "changed and unchanged expression classifications overlap"
            )
        if not set(classified["valid_changed_expressions"]).issubset(generated):
            raise ValueError(
                "changed expression classification was not generated"
            )
        if not set(classified["valid_unchanged_expressions"]).issubset(
            generated
        ):
            raise ValueError(
                "unchanged expression classification was not generated"
            )


class BuildAnswerChoicesRunner:
    """Invoke canonical step 4 to construct local-effect answer choices."""

    def run_instance(self, context: StageContext) -> StageResult:
        validation_result = context.upstream_results.get(
            "validate-candidate-expressions"
        )
        if validation_result is None:
            raise StageExecutionError(
                "build-answer-choices requires validated candidate output",
                category="missing_upstream_result",
                retryable=False,
            )
        if validation_result.outcome == "skipped":
            result = StageResult.skipped(
                validation_result.reason or "no_candidate_expressions",
                {
                    "instance_id": context.instance.instance_id,
                    "changed_count": 0,
                    "unchanged_count": 0,
                },
            )
            self.validate_result(result.to_stored())
            return result

        validated = validation_result.data.get("validated_candidates")
        if not isinstance(validated, dict):
            raise StageExecutionError(
                "validated candidate output is not a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )
        changed = validated.get("valid_changed_expressions")
        unchanged = validated.get("valid_unchanged_expressions")
        if not isinstance(changed, list) or not isinstance(unchanged, list):
            raise StageExecutionError(
                "validated candidate output has no expression pools",
                category="canonical_output_invalid",
                retryable=False,
            )
        changed_count = len(changed)
        unchanged_count = len(unchanged)
        if (
            changed_count < context.config.choice_minimum_changed
            or unchanged_count < context.config.choice_minimum_unchanged
        ):
            result = StageResult.skipped(
                "insufficient_expression_pool",
                {
                    "instance_id": context.instance.instance_id,
                    "changed_count": changed_count,
                    "unchanged_count": unchanged_count,
                },
            )
            self.validate_result(result.to_stored())
            return result

        step3_path = context.attempt_directory / "step3.json"
        atomic_write_json(
            step3_path,
            {
                context.submission_id: {
                    context.instance.instance_id: validated,
                }
            },
        )
        output_path = context.attempt_directory / "step4.json"
        run_canonical_module(
            BUILD_STEP4_MODULE,
            (
                "--agent",
                context.submission_id,
                "--instance-ids",
                context.instance.instance_id,
                "--step3-path",
                str(step3_path),
                "--output-path",
                str(output_path),
                "--correct-choices",
                str(context.config.choice_correct_count),
                "--incorrect-choices",
                str(context.config.choice_incorrect_count),
                "--minimum-changed",
                str(context.config.choice_minimum_changed),
                "--minimum-unchanged",
                str(context.config.choice_minimum_unchanged),
                "--mmr-weight",
                str(context.config.choice_mmr_weight),
                "--random-seed",
                str(context.config.choice_random_seed),
                "--agent-workers",
                str(context.config.choice_agent_workers),
                "--no-prepare-intent",
            ),
            context,
            timeout=context.config.choice_command_timeout_seconds,
            retryable_nonzero=True,
        )

        payload = _read_json(output_path)
        if not isinstance(payload, dict):
            raise StageExecutionError(
                "answer-choice output must be a JSON object",
                category="canonical_output_invalid",
                retryable=False,
            )
        agent_results = payload.get(context.submission_id)
        if not isinstance(agent_results, dict):
            raise StageExecutionError(
                "answer-choice output lacks the submission ID",
                category="canonical_output_missing",
                retryable=True,
            )
        question = agent_results.get(context.instance.instance_id)
        if not isinstance(question, dict):
            raise StageExecutionError(
                "answer-choice output lacks a valid instance result",
                category="canonical_output_missing",
                retryable=True,
            )

        answer_values = self._answer_values(question)
        is_fallback = bool(validated.get("is_fallback_to_gold", False))
        if is_fallback:
            if answer_values != [NONE_OF_THE_ABOVE_CHOICE]:
                raise StageExecutionError(
                    "gold fallback must select the no-effect choice",
                    category="canonical_output_invalid",
                    retryable=False,
                )
        elif not set(answer_values).issubset(set(changed)):
            raise StageExecutionError(
                "answer-choice output selects an expression that did not change",
                category="canonical_output_invalid",
                retryable=False,
            )

        result = StageResult.completed(
            {
                "instance_id": context.instance.instance_id,
                "question": question,
                "correct_expressions": answer_values,
                "is_fallback_to_gold": is_fallback,
            }
        )
        self.validate_result(result.to_stored())
        return result

    @staticmethod
    def _answer_values(question: dict) -> list[str]:
        choices = question.get("choices")
        answers = question.get("answer")
        if not isinstance(choices, list) or not all(
            isinstance(choice, str) and choice.strip() for choice in choices
        ):
            raise StageExecutionError(
                "answer choices must contain nonempty strings",
                category="canonical_output_invalid",
                retryable=False,
            )
        if len(choices) != len(set(choices)):
            raise StageExecutionError(
                "answer choices must be unique",
                category="canonical_output_invalid",
                retryable=False,
            )
        if choices[-2:] != [NONE_OF_THE_ABOVE_CHOICE, CANNOT_INFER_CHOICE]:
            raise StageExecutionError(
                "local-effect answer choices lack the required special choices",
                category="canonical_output_invalid",
                retryable=False,
            )
        if not isinstance(answers, list) or not answers:
            raise StageExecutionError(
                "answer-choice output requires at least one answer",
                category="canonical_output_invalid",
                retryable=False,
            )
        if len(answers) != len(set(answers)) or not all(
            isinstance(answer, str)
            and len(answer) == 1
            and "a" <= answer <= "z"
            for answer in answers
        ):
            raise StageExecutionError(
                "answer labels must be unique lowercase letters",
                category="canonical_output_invalid",
                retryable=False,
            )
        indices = [ord(answer) - ord("a") for answer in answers]
        if any(index >= len(choices) for index in indices):
            raise StageExecutionError(
                "answer label is outside the answer-choice list",
                category="canonical_output_invalid",
                retryable=False,
            )
        return [choices[index] for index in indices]

    def validate_result(self, result: StoredStageResult) -> None:
        instance_id = result.data.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("answer-choice result requires a nonempty instance_id")
        if result.outcome == "skipped":
            if result.reason not in {
                "candidate_inference_disabled",
                "no_candidate_expressions",
                "insufficient_expression_pool",
            }:
                raise ValueError("answer-choice result has an unknown skip reason")
            for key in ("changed_count", "unchanged_count"):
                value = result.data.get(key)
                if (
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                ):
                    raise ValueError(
                        f"skipped answer-choice {key} must be nonnegative"
                    )
            return

        question = result.data.get("question")
        if not isinstance(question, dict):
            raise ValueError("answer-choice question must be an object")
        try:
            answer_values = self._answer_values(question)
        except StageExecutionError as error:
            raise ValueError(str(error)) from error
        correct_expressions = result.data.get("correct_expressions")
        if correct_expressions != answer_values:
            raise ValueError("stored correct expressions do not match the answers")
        is_fallback = result.data.get("is_fallback_to_gold")
        if not isinstance(is_fallback, bool):
            raise ValueError("answer-choice fallback state must be a boolean")
        if is_fallback and answer_values != [NONE_OF_THE_ABOVE_CHOICE]:
            raise ValueError("gold fallback must select the no-effect choice")


class ExportQuestionArtifactsRunner:
    """Invoke canonical step 5 for one local-effect question."""

    def run_instance(self, context: StageContext) -> StageResult:
        if not SAFE_ARTIFACT_ID.fullmatch(context.submission_id):
            raise StageExecutionError(
                "submission ID is unsafe for artifact filenames",
                category="invalid_submission_id",
                retryable=False,
            )
        choice_result = context.upstream_results.get("build-answer-choices")
        if choice_result is None:
            raise StageExecutionError(
                "export-question-artifacts requires answer-choice output",
                category="missing_upstream_result",
                retryable=False,
            )
        if choice_result.outcome == "skipped":
            result = StageResult.skipped(
                choice_result.reason or "no_candidate_expressions",
                {"instance_id": context.instance.instance_id},
            )
            self.validate_result(result.to_stored())
            return result

        question = choice_result.data.get("question")
        if not isinstance(question, dict):
            raise StageExecutionError(
                "answer-choice output has no question object",
                category="canonical_output_invalid",
                retryable=False,
            )

        step4_path = context.attempt_directory / "step4.json"
        atomic_write_json(
            step4_path,
            {
                context.submission_id: {
                    context.instance.instance_id: question,
                }
            },
        )
        export_root = context.attempt_directory / "artifacts"
        context_directory = export_root / "context"
        ground_truth_directory = export_root / "ground_truths"
        run_canonical_module(
            BUILD_STEP5_MODULE,
            (
                "--kind",
                "effect",
                "--agent",
                context.submission_id,
                "--instance-ids",
                context.instance.instance_id,
                "--effect-step4-path",
                str(step4_path),
                "--context-dir",
                str(context_directory),
                "--ground-truth-dir",
                str(ground_truth_directory),
                "--parameter-max-characters",
                str(context.config.export_parameter_max_characters),
            ),
            context,
            timeout=context.config.export_command_timeout_seconds,
            retryable_nonzero=True,
        )

        filename = f"local_effect__{context.submission_id}.json"
        raw_context = _read_json(context_directory / filename)
        raw_ground_truth = _read_json(ground_truth_directory / filename)
        if not isinstance(raw_context, dict) or not isinstance(
            raw_ground_truth, dict
        ):
            raise StageExecutionError(
                "exported context and ground truth must be JSON objects",
                category="canonical_output_invalid",
                retryable=False,
            )
        instance_id = context.instance.instance_id
        if set(raw_context) != {instance_id} or set(raw_ground_truth) != {
            instance_id
        }:
            raise StageExecutionError(
                "exported artifacts do not contain exactly the requested instance",
                category="canonical_output_invalid",
                retryable=False,
            )

        result = StageResult.completed(
            {
                "instance_id": instance_id,
                "context": raw_context[instance_id],
                "ground_truth": raw_ground_truth[instance_id],
            }
        )
        self.validate_result(result.to_stored())
        return result

    def validate_result(self, result: StoredStageResult) -> None:
        instance_id = result.data.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("export result requires a nonempty instance_id")
        if result.outcome == "skipped":
            if result.reason not in {
                "candidate_inference_disabled",
                "no_candidate_expressions",
                "insufficient_expression_pool",
            }:
                raise ValueError("export result has an unknown skip reason")
            return
        try:
            context = LocalEffectContext.model_validate(
                result.data.get("context")
            )
            ground_truth = AnswerGroundTruth.model_validate(
                result.data.get("ground_truth")
            )
        except ValidationError as error:
            raise ValueError(f"exported local-effect artifact is invalid: {error}") from error
        choice_count = len(context.choices)
        if any(
            ord(answer) - ord("a") >= choice_count
            for answer in ground_truth.answer
        ):
            raise ValueError("exported answer refers to a missing choice")
