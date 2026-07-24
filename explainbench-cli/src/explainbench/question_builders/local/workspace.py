"""Versioned workspace storage for local-effect question construction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Sequence

from pydantic import Field, ValidationError

from explainbench import __version__
from explainbench.question_builders.common.artifacts import (
    validate_artifact_manifest,
)
from explainbench.question_builders.common.atomic_files import atomic_write_json
from explainbench.question_builders.common.fingerprints import (
    fingerprint_file,
    fingerprint_value,
)
from explainbench.question_builders.common.orchestration import StageDefinition
from explainbench.question_builders.common.status import (
    InstanceStageAttempt,
    InstanceStageStatus,
    StageCheckpointSummary,
    StoredStageResult,
)
from explainbench.schemas import StrictModel, Submission


WORKSPACE_SCHEMA_VERSION = 1


class LocalWorkspaceError(RuntimeError):
    """Raised when a local-builder workspace is missing or incompatible."""


class LocalWorkspaceManifest(StrictModel):
    """Top-level identity and aggregate state for a builder workspace."""

    schema_version: Literal[1] = WORKSPACE_SCHEMA_VERSION
    builder: Literal["local-effect"] = "local-effect"
    explainbench_version: str
    submission_id: str
    submission_fingerprint: str
    instance_patch_fingerprints: dict[str, str]
    instance_ids: list[str]
    created_at: str
    updated_at: str
    stage_summaries: dict[str, StageCheckpointSummary] = Field(
        default_factory=dict
    )
    artifact_output: str | None = None
    artifact_fingerprint: str | None = None
    artifact_files: dict[str, str] = Field(default_factory=dict)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LocalWorkspaceError(
            f"cannot read workspace file {path}: {error}"
        ) from error


def _patch_fingerprints(submission: Submission) -> dict[str, str]:
    return {
        instance.instance_id: fingerprint_value(instance.model_patch)
        for instance in submission.instances
    }


def _upgrade_status_payload(payload: object) -> object:
    """Convert a version 1 instance status to the version 2 schema."""

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return payload
    attempts = payload.get("attempts", 0)
    if not isinstance(attempts, int) or isinstance(attempts, bool):
        return payload
    upgraded = {
        key: value
        for key, value in payload.items()
        if key not in {"schema_version", "fingerprint", "attempts"}
    }
    upgraded.update(
        {
            "schema_version": 2,
            "semantic_fingerprint": payload.get("fingerprint"),
            "execution_fingerprint": None,
            "retry_cycle": 1 if attempts > 0 else 0,
            "cycle_attempt": attempts,
            "total_attempts": attempts,
        }
    )
    return upgraded


class LocalBuilderWorkspace:
    """Read and atomically update one local-effect build workspace."""

    def __init__(self, root: str | Path, manifest: LocalWorkspaceManifest) -> None:
        self.root = Path(root)
        self.manifest = manifest

    @classmethod
    def prepare(
        cls,
        root: str | Path,
        submission: Submission,
        *,
        resume: bool,
        stage_names: Sequence[str],
    ) -> "LocalBuilderWorkspace":
        workspace_root = Path(root)
        workspace_root.mkdir(parents=True, exist_ok=True)
        manifest_path = workspace_root / "manifest.json"
        patch_fingerprints = _patch_fingerprints(submission)
        submission_fingerprint = fingerprint_value(
            submission.model_dump(mode="json")
        )

        if manifest_path.exists():
            if not resume:
                raise LocalWorkspaceError(
                    f"workspace already contains a build: {workspace_root}; "
                    "use --resume to reuse compatible checkpoints"
                )
            try:
                manifest = LocalWorkspaceManifest.model_validate(
                    _read_json(manifest_path)
                )
            except ValidationError as error:
                raise LocalWorkspaceError(
                    f"workspace manifest is invalid: {error}"
                ) from error
            if manifest.submission_id != submission.submission_id:
                raise LocalWorkspaceError(
                    "workspace belongs to submission "
                    f"{manifest.submission_id!r}, not {submission.submission_id!r}"
                )
            workspace = cls(workspace_root, manifest)
            changed_instances = {
                instance_id
                for instance_id, checksum in patch_fingerprints.items()
                if manifest.instance_patch_fingerprints.get(instance_id) != checksum
            }
            for instance_id in changed_instances:
                workspace.mark_stale(
                    stage_names,
                    instance_id,
                    "submitted patch changed",
                )
            manifest.submission_fingerprint = submission_fingerprint
            manifest.instance_patch_fingerprints = patch_fingerprints
            manifest.instance_ids = [
                instance.instance_id for instance in submission.instances
            ]
            manifest.explainbench_version = __version__
            manifest.updated_at = _now()
            workspace._write_manifest()
        else:
            unexpected = [
                item.name
                for item in workspace_root.iterdir()
                if item.name != "workspace.lock"
            ]
            if unexpected:
                raise LocalWorkspaceError(
                    f"workspace is nonempty but has no manifest: {workspace_root}"
                )
            created_at = _now()
            workspace = cls(
                workspace_root,
                LocalWorkspaceManifest(
                    explainbench_version=__version__,
                    submission_id=submission.submission_id,
                    submission_fingerprint=submission_fingerprint,
                    instance_patch_fingerprints=patch_fingerprints,
                    instance_ids=[
                        instance.instance_id for instance in submission.instances
                    ],
                    created_at=created_at,
                    updated_at=created_at,
                ),
            )
            workspace._write_manifest()

        workspace._migrate_statuses(stage_names)

        atomic_write_json(
            workspace_root / "input" / "submission.json",
            submission.model_dump(mode="json"),
        )
        return workspace

    @classmethod
    def inspect(cls, root: str | Path) -> "LocalBuilderWorkspace":
        workspace_root = Path(root)
        manifest_path = workspace_root / "manifest.json"
        if not manifest_path.is_file():
            raise LocalWorkspaceError(
                f"no local question-builder workspace found at {workspace_root}"
            )
        try:
            manifest = LocalWorkspaceManifest.model_validate(
                _read_json(manifest_path)
            )
        except ValidationError as error:
            raise LocalWorkspaceError(
                f"workspace manifest is invalid: {error}"
            ) from error
        snapshot = workspace_root / "input" / "submission.json"
        if not snapshot.is_file():
            raise LocalWorkspaceError(
                f"workspace submission snapshot is missing: {snapshot}"
            )
        snapshot_payload = _read_json(snapshot)
        if fingerprint_value(snapshot_payload) != manifest.submission_fingerprint:
            raise LocalWorkspaceError(
                "workspace submission snapshot does not match its manifest"
            )
        return cls(workspace_root, manifest)

    def _instance_directory(self, stage_name: str, instance_id: str) -> Path:
        return self.root / "stages" / stage_name / "instances" / instance_id

    def _status_path(self, stage_name: str, instance_id: str) -> Path:
        return self._instance_directory(stage_name, instance_id) / "status.json"

    def _result_path(self, stage_name: str, instance_id: str) -> Path:
        return self._instance_directory(stage_name, instance_id) / "result.json"

    def read_status(
        self, stage_name: str, instance_id: str
    ) -> InstanceStageStatus | None:
        path = self._status_path(stage_name, instance_id)
        if not path.is_file():
            return None
        try:
            return InstanceStageStatus.model_validate(
                _upgrade_status_payload(_read_json(path))
            )
        except (ValidationError, LocalWorkspaceError) as error:
            return InstanceStageStatus(
                stage=stage_name,
                instance_id=instance_id,
                state="stale",
                stale_reason=f"checkpoint status is invalid: {error}",
            )

    def write_status(self, status: InstanceStageStatus) -> None:
        atomic_write_json(
            self._status_path(status.stage, status.instance_id),
            status.model_dump(mode="json"),
        )

    def read_result(
        self, stage_name: str, instance_id: str
    ) -> StoredStageResult:
        path = self._result_path(stage_name, instance_id)
        try:
            return StoredStageResult.model_validate(_read_json(path))
        except ValidationError as error:
            raise LocalWorkspaceError(
                f"invalid checkpoint result {path}: {error}"
            ) from error

    def write_result(
        self,
        stage_name: str,
        instance_id: str,
        result: StoredStageResult,
    ) -> tuple[str, str]:
        path = self._result_path(stage_name, instance_id)
        atomic_write_json(path, result.model_dump(mode="json"))
        return path.name, fingerprint_file(path)

    def result_checksum(self, stage_name: str, instance_id: str) -> str:
        return fingerprint_file(self._result_path(stage_name, instance_id))

    def validate_result_artifacts(
        self,
        stage_name: str,
        instance_id: str,
        result: StoredStageResult,
    ) -> None:
        manifest = result.data.get("artifact_manifest")
        if manifest is None:
            return
        validate_artifact_manifest(
            manifest,
            relative_to=self._instance_directory(stage_name, instance_id),
        )

    def work_directory(self, stage_name: str, instance_id: str) -> Path:
        path = self._instance_directory(stage_name, instance_id) / "work"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def attempt_directory(
        self,
        stage_name: str,
        instance_id: str,
        total_attempt: int,
    ) -> Path:
        path = (
            self.work_directory(stage_name, instance_id)
            / f"attempt-{total_attempt}"
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    def log_directory(
        self,
        stage_name: str,
        instance_id: str,
        total_attempt: int,
    ) -> Path:
        path = (
            self.root
            / "logs"
            / stage_name
            / instance_id
            / f"attempt-{total_attempt}"
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_attempt(self, attempt: InstanceStageAttempt) -> None:
        atomic_write_json(
            self.attempt_directory(
                attempt.stage,
                attempt.instance_id,
                attempt.total_attempt,
            )
            / "attempt.json",
            attempt.model_dump(mode="json"),
        )

    def mark_stale(
        self,
        stage_names: Sequence[str],
        instance_id: str,
        reason: str,
    ) -> None:
        for stage_name in stage_names:
            current = self.read_status(stage_name, instance_id)
            if current is None or current.state == "stale":
                continue
            self.write_status(
                InstanceStageStatus(
                    stage=stage_name,
                    instance_id=instance_id,
                    state="stale",
                    semantic_fingerprint=current.semantic_fingerprint,
                    execution_fingerprint=current.execution_fingerprint,
                    retry_cycle=current.retry_cycle,
                    cycle_attempt=current.cycle_attempt,
                    total_attempts=current.total_attempts,
                    started_at=current.started_at,
                    finished_at=current.finished_at,
                    result_file=current.result_file,
                    result_checksum=current.result_checksum,
                    artifact_manifests=current.artifact_manifests,
                    stale_reason=reason,
                )
            )

    def _migrate_statuses(self, stage_names: Sequence[str]) -> None:
        for stage_name in stage_names:
            instances = self.root / "stages" / stage_name / "instances"
            if not instances.is_dir():
                continue
            for status_path in instances.glob("*/status.json"):
                try:
                    payload = _read_json(status_path)
                except LocalWorkspaceError:
                    continue
                upgraded = _upgrade_status_payload(payload)
                if upgraded != payload:
                    try:
                        status = InstanceStageStatus.model_validate(upgraded)
                    except ValidationError:
                        continue
                    atomic_write_json(
                        status_path,
                        status.model_dump(mode="json"),
                    )

    def write_stage_summary(
        self,
        definition: StageDefinition,
        semantic_config_fingerprint: str,
    ) -> None:
        counts = {
            state: 0
            for state in (
                "pending",
                "running",
                "completed",
                "skipped",
                "failed",
                "stale",
            )
        }
        for instance_id in self.manifest.instance_ids:
            status = self.read_status(definition.name, instance_id)
            counts[status.state if status is not None else "pending"] += 1
        summary = StageCheckpointSummary(
            stage=definition.name,
            implementation_version=definition.implementation_version,
            semantic_config_fingerprint=semantic_config_fingerprint,
            counts=counts,
            updated_at=_now(),
        )
        atomic_write_json(
            self.root / "stages" / definition.name / "stage.json",
            summary.model_dump(mode="json"),
        )
        self.manifest.stage_summaries[definition.name] = summary
        self.manifest.updated_at = summary.updated_at
        self._write_manifest()

    def status_counts(self, stage_name: str) -> dict[str, int]:
        counts = {
            state: 0
            for state in (
                "pending",
                "running",
                "completed",
                "skipped",
                "failed",
                "stale",
            )
        }
        for instance_id in self.manifest.instance_ids:
            status = self.read_status(stage_name, instance_id)
            counts[status.state if status is not None else "pending"] += 1
        return counts

    def failures(self) -> list[InstanceStageStatus]:
        failures: list[InstanceStageStatus] = []
        for stage_name in self.manifest.stage_summaries:
            for instance_id in self.manifest.instance_ids:
                status = self.read_status(stage_name, instance_id)
                if status is not None and status.state == "failed":
                    failures.append(status)
        return failures

    def record_artifact_publication(
        self,
        *,
        output: Path,
        fingerprint: str,
        files: dict[str, str],
    ) -> None:
        """Record one complete evaluator artifact publication."""

        self.manifest.artifact_output = str(output)
        self.manifest.artifact_fingerprint = fingerprint
        self.manifest.artifact_files = dict(files)
        self.manifest.updated_at = _now()
        self._write_manifest()

    def _write_manifest(self) -> None:
        atomic_write_json(
            self.root / "manifest.json",
            self.manifest.model_dump(mode="json"),
        )
