"""Export completed local-effect questions using the evaluator contract."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from explainbench import __version__
from explainbench.evaluation.schemas import (
    AnswerGroundTruth,
    LocalEffectContext,
)
from explainbench.question_builders.common.atomic_files import atomic_write_json
from explainbench.question_builders.common.fingerprints import fingerprint_file
from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
    StageFinalizationContext,
    StageResult,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.question_builders.local.stages.build_answer_choices import (
    AnswerChoicesResult,
)
from explainbench.schemas import StrictModel


class ExportedQuestionResult(StrictModel):
    """One validated context and ground-truth pair ready for aggregation."""

    context: LocalEffectContext
    ground_truth: AnswerGroundTruth
    used_gold_fallback: bool = False


class LocalEffectArtifactManifest(StrictModel):
    """Identity and checksums for one published artifact bundle."""

    schema_version: Literal[1] = 1
    explainbench_version: str
    builder: Literal["local"] = "local"
    submission_id: str
    submission_fingerprint: str
    included_instance_ids: list[str]
    skipped_instance_ids: list[str] = Field(default_factory=list)
    failed_instance_ids: list[str] = Field(default_factory=list)
    gold_fallback_instance_ids: list[str] = Field(default_factory=list)
    context_checksum: str
    ground_truth_checksum: str
    semantic_configuration: dict[str, Any]


def format_function_parameters(value: Any, *, limit: int = 20_000) -> str:
    """Preserve legacy printable formatting with a bounded prompt size."""

    output = io.StringIO()
    print(value, file=output)
    contents = output.getvalue()
    if len(contents) > limit:
        return contents[:limit] + " ...(truncated)"
    return contents


def build_context_and_ground_truth(
    question: AnswerChoicesResult,
) -> tuple[LocalEffectContext, AnswerGroundTruth]:
    metadata = question.metadata
    try:
        context = LocalEffectContext(
            function_code_before_patch=metadata["function_code_before_patch"],
            function_parameters_before_patch=format_function_parameters(
                metadata["buggy_function_param"]
            ),
            line=metadata["location"],
            choices=question.choices,
            before_or_after=metadata["before_or_after"],
        )
        ground_truth = AnswerGroundTruth(answer=question.answer)
    except KeyError as error:
        raise ValueError(f"question metadata is missing {error.args[0]!r}") from error
    return context, ground_truth


class ExportQuestionArtifactsRunner:
    """Validate per-instance records and atomically publish their bundle."""

    def run_instance(self, context: StageContext) -> StageResult:
        try:
            choices = AnswerChoicesResult.model_validate(
                context.upstream_results["build-answer-choices"].data
            )
            question_context, ground_truth = build_context_and_ground_truth(
                choices
            )
        except (KeyError, ValueError) as error:
            raise StageExecutionError(
                f"could not export local-effect question: {error}",
                category="question_artifact_invalid",
                retryable=False,
            ) from error
        output = ExportedQuestionResult(
            context=question_context,
            ground_truth=ground_truth,
            used_gold_fallback=choices.is_fallback_to_gold,
        )
        return StageResult.completed(output.model_dump(mode="json"))

    def validate_result(self, result: StoredStageResult) -> None:
        ExportedQuestionResult.model_validate(result.data)

    def finalize_stage(self, context: StageFinalizationContext) -> None:
        output = context.config.artifact_output
        if output is None:
            raise StageExecutionError(
                "artifact output directory is required for export",
                category="artifact_output_missing",
            )
        workspace = context.workspace
        contexts: dict[str, dict[str, Any]] = {}
        ground_truths: dict[str, dict[str, Any]] = {}
        fallback_ids: list[str] = []
        included_ids: list[str] = []
        skipped_ids: set[str] = set()
        failed_ids: set[str] = set()
        failure_records: dict[str, list[dict[str, str]]] = {}

        for instance in context.instances:
            instance_id = instance.instance_id
            status = workspace.read_status(
                "export-question-artifacts", instance_id
            )
            if status is not None and status.state == "completed":
                stored = workspace.read_result(
                    "export-question-artifacts", instance_id
                )
                exported = ExportedQuestionResult.model_validate(stored.data)
                contexts[instance_id] = exported.context.model_dump(mode="json")
                ground_truths[instance_id] = exported.ground_truth.model_dump(
                    mode="json"
                )
                included_ids.append(instance_id)
                if exported.used_gold_fallback:
                    fallback_ids.append(instance_id)
                continue

            records = []
            for stage_name in workspace.manifest.stage_summaries:
                stage_status = workspace.read_status(stage_name, instance_id)
                if stage_status is None:
                    continue
                if stage_status.state == "skipped":
                    skipped_ids.add(instance_id)
                    records.append(
                        {
                            "stage": stage_name,
                            "state": "skipped",
                            "message": "stage was intentionally skipped",
                        }
                    )
                elif stage_status.state == "failed":
                    failed_ids.add(instance_id)
                    records.append(
                        {
                            "stage": stage_name,
                            "state": "failed",
                            "message": (
                                stage_status.failure.message
                                if stage_status.failure is not None
                                else "stage failed"
                            ),
                        }
                    )
            if records:
                failure_records[instance_id] = records

        if not included_ids:
            raise StageExecutionError(
                "no completed local-effect questions are available to export",
                category="no_exportable_questions",
            )
        self._publish(
            Path(output),
            workspace=workspace,
            contexts=contexts,
            ground_truths=ground_truths,
            failures=failure_records,
            included_ids=sorted(included_ids),
            skipped_ids=sorted(skipped_ids - set(included_ids)),
            failed_ids=sorted(failed_ids - set(included_ids)),
            fallback_ids=sorted(fallback_ids),
            config=context.config,
        )
        workspace.record_artifact_output(output)

    def _publish(
        self,
        output: Path,
        *,
        workspace,
        contexts: dict[str, dict[str, Any]],
        ground_truths: dict[str, dict[str, Any]],
        failures: dict[str, list[dict[str, str]]],
        included_ids: list[str],
        skipped_ids: list[str],
        failed_ids: list[str],
        fallback_ids: list[str],
        config,
    ) -> None:
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent)
        )
        backup = output.with_name(f".{output.name}.previous")
        try:
            filename = f"local_effect__{workspace.manifest.submission_id}.json"
            context_path = staging / "context" / filename
            ground_truth_path = staging / "ground_truths" / filename
            atomic_write_json(context_path, contexts)
            atomic_write_json(ground_truth_path, ground_truths)
            atomic_write_json(staging / "failures.json", failures)
            manifest = LocalEffectArtifactManifest(
                explainbench_version=__version__,
                submission_id=workspace.manifest.submission_id,
                submission_fingerprint=workspace.manifest.submission_fingerprint,
                included_instance_ids=included_ids,
                skipped_instance_ids=skipped_ids,
                failed_instance_ids=failed_ids,
                gold_fallback_instance_ids=fallback_ids,
                context_checksum=fingerprint_file(context_path),
                ground_truth_checksum=fingerprint_file(ground_truth_path),
                semantic_configuration={
                    "correct_choices": config.correct_choices,
                    "incorrect_choices": config.incorrect_choices,
                    "mmr_weight": config.mmr_weight,
                    "random_seed": config.random_seed,
                },
            )
            atomic_write_json(staging / "manifest.json", manifest.model_dump(mode="json"))

            if backup.exists():
                shutil.rmtree(backup)
            if output.exists():
                os.replace(output, backup)
            try:
                os.replace(staging, output)
            except BaseException:
                if backup.exists() and not output.exists():
                    os.replace(backup, output)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

