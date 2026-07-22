"""Dependency-aware, resumable orchestration for question-builder stages."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from explainbench.question_builders.common.fingerprints import fingerprint_value
from explainbench.question_builders.common.status import (
    InstanceStageAttempt,
    InstanceStageStatus,
    StageFailure,
    StoredStageResult,
)
from explainbench.schemas import SubmissionInstance


class QuestionBuilderError(RuntimeError):
    """Base error for question-builder setup or orchestration failures."""


class MissingPrerequisiteError(QuestionBuilderError):
    """Raised when an individually invoked stage lacks upstream results."""


class StageExecutionError(RuntimeError):
    """A categorized failure raised by a stage implementation."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "stage_execution_error",
        retryable: bool = False,
    ) -> None:
        self.category = category
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class StageResult:
    """Successful or intentional-skip output returned by a stage runner."""

    outcome: str
    data: Mapping[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @classmethod
    def completed(cls, data: Mapping[str, Any] | None = None) -> "StageResult":
        return cls(outcome="completed", data=data or {})

    @classmethod
    def skipped(
        cls,
        reason: str,
        data: Mapping[str, Any] | None = None,
    ) -> "StageResult":
        return cls(outcome="skipped", data=data or {}, reason=reason)

    def to_stored(self) -> StoredStageResult:
        return StoredStageResult.model_validate(
            {
                "outcome": self.outcome,
                "data": dict(self.data),
                "reason": self.reason,
            }
        )


@dataclass(frozen=True)
class StageContext:
    """All explicit inputs available to one instance-stage execution."""

    submission_id: str
    instance: SubmissionInstance
    workspace: Path
    work_directory: Path
    attempt_directory: Path
    log_directory: Path
    retry_cycle: int
    cycle_attempt: int
    total_attempt: int
    upstream_results: Mapping[str, StoredStageResult]
    config: Any


class StageRunner(Protocol):
    """Implementation contract for one question-builder stage."""

    def run_instance(self, context: StageContext) -> StageResult:
        ...

    def validate_result(self, result: StoredStageResult) -> None:
        ...


SemanticInputs = Callable[[Any], Mapping[str, Any]]
ResourceInputs = Callable[[Any], Mapping[str, Any]]


def _no_semantic_inputs(config: Any) -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True)
class StageDefinition:
    """One named stage and its declared dependencies."""

    name: str
    description: str
    dependencies: tuple[str, ...]
    implementation_version: str
    runner: StageRunner
    semantic_inputs: SemanticInputs = _no_semantic_inputs
    resource_inputs: ResourceInputs = _no_semantic_inputs
    execution_inputs: ResourceInputs = _no_semantic_inputs
    accepts_skipped_dependencies: bool = False


class StageRegistry:
    """Validate and expose a deterministic stage dependency graph."""

    def __init__(self, definitions: Sequence[StageDefinition]) -> None:
        if not definitions:
            raise ValueError("a stage registry must contain at least one stage")
        self._definitions: dict[str, StageDefinition] = {}
        for definition in definitions:
            if not definition.name or definition.name in self._definitions:
                raise ValueError(
                    f"duplicate or blank stage name: {definition.name!r}"
                )
            self._definitions[definition.name] = definition
        for definition in definitions:
            unknown = [
                dependency
                for dependency in definition.dependencies
                if dependency not in self._definitions
            ]
            if unknown:
                raise ValueError(
                    f"stage {definition.name!r} has unknown dependencies: "
                    f"{', '.join(unknown)}"
                )
        self._ordered_names = self._topological_order()

    @property
    def names(self) -> tuple[str, ...]:
        return self._ordered_names

    @property
    def definitions(self) -> tuple[StageDefinition, ...]:
        return tuple(self._definitions[name] for name in self._ordered_names)

    def __contains__(self, name: str) -> bool:
        return name in self._definitions

    def __getitem__(self, name: str) -> StageDefinition:
        try:
            return self._definitions[name]
        except KeyError as error:
            raise KeyError(f"unknown question-builder stage {name!r}") from error

    def downstream(self, stage_name: str) -> tuple[str, ...]:
        """Return a stage and every transitive dependent in execution order."""

        if stage_name not in self:
            raise KeyError(f"unknown question-builder stage {stage_name!r}")
        affected = {stage_name}
        changed = True
        while changed:
            changed = False
            for definition in self.definitions:
                if definition.name in affected:
                    continue
                if any(item in affected for item in definition.dependencies):
                    affected.add(definition.name)
                    changed = True
        return tuple(name for name in self.names if name in affected)

    def _topological_order(self) -> tuple[str, ...]:
        visiting: set[str] = set()
        visited: set[str] = set()
        ordered: list[str] = []

        def visit(name: str) -> None:
            if name in visiting:
                raise ValueError("question-builder stage dependencies contain a cycle")
            if name in visited:
                return
            visiting.add(name)
            for dependency in self._definitions[name].dependencies:
                visit(dependency)
            visiting.remove(name)
            visited.add(name)
            ordered.append(name)

        for stage_name in self._definitions:
            visit(stage_name)
        return tuple(ordered)


class BuilderWorkspace(Protocol):
    """Storage operations required by the generic orchestrator."""

    root: Path

    def read_status(
        self, stage_name: str, instance_id: str
    ) -> InstanceStageStatus | None:
        ...

    def write_status(self, status: InstanceStageStatus) -> None:
        ...

    def read_result(
        self, stage_name: str, instance_id: str
    ) -> StoredStageResult:
        ...

    def write_result(
        self,
        stage_name: str,
        instance_id: str,
        result: StoredStageResult,
    ) -> tuple[str, str]:
        ...

    def result_checksum(self, stage_name: str, instance_id: str) -> str:
        ...

    def validate_result_artifacts(
        self,
        stage_name: str,
        instance_id: str,
        result: StoredStageResult,
    ) -> None:
        ...

    def work_directory(self, stage_name: str, instance_id: str) -> Path:
        ...

    def attempt_directory(
        self,
        stage_name: str,
        instance_id: str,
        total_attempt: int,
    ) -> Path:
        ...

    def log_directory(
        self,
        stage_name: str,
        instance_id: str,
        total_attempt: int,
    ) -> Path:
        ...

    def write_attempt(self, attempt: InstanceStageAttempt) -> None:
        ...

    def mark_stale(
        self,
        stage_names: Sequence[str],
        instance_id: str,
        reason: str,
    ) -> None:
        ...

    def write_stage_summary(
        self,
        definition: StageDefinition,
        semantic_config_fingerprint: str,
    ) -> None:
        ...


@dataclass(frozen=True)
class StageRunSummary:
    """Counts from one orchestration pass over a stage."""

    stage: str
    requested: int
    completed: int = 0
    skipped: int = 0
    reused: int = 0
    failed: int = 0
    blocked: int = 0

    @property
    def has_failures(self) -> bool:
        return self.failed > 0 or self.blocked > 0


def _now() -> str:
    return datetime.now(UTC).isoformat()


class BuilderOrchestrator:
    """Run registered stages with durable per-instance checkpoints."""

    def __init__(
        self,
        *,
        registry: StageRegistry,
        workspace: BuilderWorkspace,
        instances: Sequence[SubmissionInstance],
        submission_id: str,
        config: Any,
        max_attempts: int,
        max_workers: int = 1,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self.registry = registry
        self.workspace = workspace
        self.instances = tuple(instances)
        self.submission_id = submission_id
        self.config = config
        self.max_attempts = max_attempts
        self.max_workers = max_workers

    def run_all(self) -> tuple[StageRunSummary, ...]:
        """Run every stage while allowing unaffected instances to progress."""

        return tuple(
            self.run_stage(stage_name, require_all_prerequisites=False)
            for stage_name in self.registry.names
        )

    def run_stage(
        self,
        stage_name: str,
        *,
        require_all_prerequisites: bool = True,
    ) -> StageRunSummary:
        """Run one stage, reusing only compatible validated checkpoints."""

        definition = self.registry[stage_name]
        resolved_dependencies: dict[
            str, dict[str, StoredStageResult]
        ] = {}
        missing: list[str] = []
        for instance in self.instances:
            upstream = self._resolve_dependencies(definition, instance)
            if upstream is None:
                missing.append(instance.instance_id)
            else:
                resolved_dependencies[instance.instance_id] = upstream

        if missing and require_all_prerequisites:
            prerequisite_names = ", ".join(definition.dependencies)
            preview = ", ".join(missing[:5])
            if len(missing) > 5:
                preview += f", and {len(missing) - 5} more"
            raise MissingPrerequisiteError(
                f"stage {stage_name!r} requires compatible results from "
                f"[{prerequisite_names}] for: {preview}. Run the missing "
                "prerequisite stage(s), or use 'question-builder local run'."
            )

        def process(instance: SubmissionInstance) -> str:
            upstream = resolved_dependencies.get(instance.instance_id)
            if upstream is None:
                return "blocked"
            return self._run_instance(definition, instance, upstream)

        if self.max_workers == 1:
            outcomes = [process(instance) for instance in self.instances]
        else:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [
                    executor.submit(process, instance) for instance in self.instances
                ]
                outcomes = [future.result() for future in as_completed(futures)]

        completed = skipped = reused = failed = blocked = 0
        for outcome in outcomes:
            if outcome == "completed":
                completed += 1
            elif outcome == "skipped":
                skipped += 1
            elif outcome == "reused":
                reused += 1
            elif outcome == "blocked":
                blocked += 1
            else:
                failed += 1

        config_fingerprint = fingerprint_value(
            dict(definition.semantic_inputs(self.config))
        )
        self.workspace.write_stage_summary(definition, config_fingerprint)
        return StageRunSummary(
            stage=stage_name,
            requested=len(self.instances),
            completed=completed,
            skipped=skipped,
            reused=reused,
            failed=failed,
            blocked=blocked,
        )

    def _resolve_dependencies(
        self,
        definition: StageDefinition,
        instance: SubmissionInstance,
    ) -> dict[str, StoredStageResult] | None:
        results: dict[str, StoredStageResult] = {}
        for dependency in definition.dependencies:
            result = self._compatible_result(dependency, instance)
            if result is None:
                return None
            if (
                result.outcome == "skipped"
                and not definition.accepts_skipped_dependencies
            ):
                return None
            results[dependency] = result
        return results

    def _compatible_result(
        self,
        stage_name: str,
        instance: SubmissionInstance,
    ) -> StoredStageResult | None:
        definition = self.registry[stage_name]
        upstream = self._resolve_dependencies(definition, instance)
        if upstream is None:
            return None
        expected = self._semantic_fingerprint(definition, instance, upstream)
        status = self.workspace.read_status(stage_name, instance.instance_id)
        if status is None or status.state not in {"completed", "skipped"}:
            return None
        if status.semantic_fingerprint != expected:
            self._invalidate(
                stage_name,
                instance.instance_id,
                "semantic inputs changed",
            )
            return None
        try:
            result = self.workspace.read_result(stage_name, instance.instance_id)
            checksum = self.workspace.result_checksum(
                stage_name, instance.instance_id
            )
            if checksum != status.result_checksum:
                raise ValueError("result checksum does not match checkpoint")
            definition.runner.validate_result(result)
            self.workspace.validate_result_artifacts(
                stage_name,
                instance.instance_id,
                result,
            )
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            self._invalidate(
                stage_name,
                instance.instance_id,
                f"checkpoint result is missing or corrupt: {error}",
            )
            return None
        return result

    def _run_instance(
        self,
        definition: StageDefinition,
        instance: SubmissionInstance,
        upstream: Mapping[str, StoredStageResult],
    ) -> str:
        compatible = self._compatible_result(definition.name, instance)
        if compatible is not None:
            return "reused"

        semantic_fingerprint = self._semantic_fingerprint(
            definition,
            instance,
            upstream,
        )
        execution_fingerprint = self._execution_fingerprint(definition)
        previous = self.workspace.read_status(
            definition.name, instance.instance_id
        )
        if (
            previous is not None
            and previous.state == "failed"
            and previous.semantic_fingerprint == semantic_fingerprint
            and previous.failure is not None
            and not previous.failure.retryable
        ):
            return "failed"

        if previous is not None and previous.state == "running":
            self._record_interruption(previous)

        total_attempts = previous.total_attempts if previous is not None else 0
        retry_cycle = (
            previous.retry_cycle + 1
            if previous is not None and previous.retry_cycle > 0
            else 1
        )
        cycle_attempt = 0

        while cycle_attempt < self.max_attempts:
            cycle_attempt += 1
            total_attempts += 1
            started_at = _now()
            attempt = InstanceStageAttempt(
                stage=definition.name,
                instance_id=instance.instance_id,
                state="running",
                semantic_fingerprint=semantic_fingerprint,
                execution_fingerprint=execution_fingerprint,
                retry_cycle=retry_cycle,
                cycle_attempt=cycle_attempt,
                total_attempt=total_attempts,
                started_at=started_at,
            )
            self.workspace.write_status(
                InstanceStageStatus(
                    stage=definition.name,
                    instance_id=instance.instance_id,
                    state="running",
                    semantic_fingerprint=semantic_fingerprint,
                    execution_fingerprint=execution_fingerprint,
                    retry_cycle=retry_cycle,
                    cycle_attempt=cycle_attempt,
                    total_attempts=total_attempts,
                    started_at=started_at,
                )
            )
            self.workspace.write_attempt(attempt)
            attempt_directory = self.workspace.attempt_directory(
                definition.name,
                instance.instance_id,
                total_attempts,
            )
            context = StageContext(
                submission_id=self.submission_id,
                instance=instance,
                workspace=self.workspace.root,
                work_directory=self.workspace.work_directory(
                    definition.name, instance.instance_id
                ),
                attempt_directory=attempt_directory,
                log_directory=self.workspace.log_directory(
                    definition.name,
                    instance.instance_id,
                    total_attempts,
                ),
                retry_cycle=retry_cycle,
                cycle_attempt=cycle_attempt,
                total_attempt=total_attempts,
                upstream_results=dict(upstream),
                config=self.config,
            )
            try:
                result = definition.runner.run_instance(context).to_stored()
                definition.runner.validate_result(result)
                self.workspace.validate_result_artifacts(
                    definition.name,
                    instance.instance_id,
                    result,
                )
                result_file, result_checksum = self.workspace.write_result(
                    definition.name,
                    instance.instance_id,
                    result,
                )
                finished_at = _now()
                self.workspace.write_attempt(
                    InstanceStageAttempt.model_validate(
                        {
                            **attempt.model_dump(mode="python"),
                            "state": result.outcome,
                            "finished_at": finished_at,
                        }
                    )
                )
                self.workspace.write_status(
                    InstanceStageStatus(
                        stage=definition.name,
                        instance_id=instance.instance_id,
                        state=result.outcome,
                        semantic_fingerprint=semantic_fingerprint,
                        execution_fingerprint=execution_fingerprint,
                        retry_cycle=retry_cycle,
                        cycle_attempt=cycle_attempt,
                        total_attempts=total_attempts,
                        started_at=started_at,
                        finished_at=finished_at,
                        result_file=result_file,
                        result_checksum=result_checksum,
                    )
                )
                return result.outcome
            except StageExecutionError as error:
                self._record_failure(
                    definition,
                    instance,
                    semantic_fingerprint,
                    execution_fingerprint,
                    retry_cycle,
                    cycle_attempt,
                    total_attempts,
                    started_at,
                    error.category,
                    str(error),
                    error.retryable,
                )
                if not error.retryable:
                    return "failed"
            except Exception as error:
                self._record_failure(
                    definition,
                    instance,
                    semantic_fingerprint,
                    execution_fingerprint,
                    retry_cycle,
                    cycle_attempt,
                    total_attempts,
                    started_at,
                    "unexpected_error",
                    f"{type(error).__name__}: {error}",
                    False,
                )
                return "failed"
        return "failed"

    def _record_failure(
        self,
        definition: StageDefinition,
        instance: SubmissionInstance,
        semantic_fingerprint: str,
        execution_fingerprint: str,
        retry_cycle: int,
        cycle_attempt: int,
        total_attempts: int,
        started_at: str,
        category: str,
        message: str,
        retryable: bool,
    ) -> None:
        finished_at = _now()
        failure = StageFailure(
            category=category,
            message=message,
            retryable=retryable,
        )
        self.workspace.write_attempt(
            InstanceStageAttempt(
                stage=definition.name,
                instance_id=instance.instance_id,
                state="failed",
                semantic_fingerprint=semantic_fingerprint,
                execution_fingerprint=execution_fingerprint,
                retry_cycle=retry_cycle,
                cycle_attempt=cycle_attempt,
                total_attempt=total_attempts,
                started_at=started_at,
                finished_at=finished_at,
                failure=failure,
            )
        )
        self.workspace.write_status(
            InstanceStageStatus(
                stage=definition.name,
                instance_id=instance.instance_id,
                state="failed",
                semantic_fingerprint=semantic_fingerprint,
                execution_fingerprint=execution_fingerprint,
                retry_cycle=retry_cycle,
                cycle_attempt=cycle_attempt,
                total_attempts=total_attempts,
                started_at=started_at,
                finished_at=finished_at,
                failure=failure,
            )
        )

    def _record_interruption(self, previous: InstanceStageStatus) -> None:
        if previous.total_attempts < 1:
            return
        finished_at = _now()
        failure = StageFailure(
            category="interrupted",
            message="the previous process ended before the attempt completed",
            retryable=True,
        )
        self.workspace.write_attempt(
            InstanceStageAttempt(
                stage=previous.stage,
                instance_id=previous.instance_id,
                state="interrupted",
                semantic_fingerprint=previous.semantic_fingerprint or "unknown",
                execution_fingerprint=previous.execution_fingerprint or "unknown",
                retry_cycle=max(previous.retry_cycle, 1),
                cycle_attempt=max(previous.cycle_attempt, 1),
                total_attempt=previous.total_attempts,
                started_at=previous.started_at or finished_at,
                finished_at=finished_at,
                failure=failure,
            )
        )
        self.workspace.write_status(
            InstanceStageStatus.model_validate(
                {
                    **previous.model_dump(mode="python"),
                    "state": "failed",
                    "finished_at": finished_at,
                    "failure": failure,
                }
            )
        )

    def _semantic_fingerprint(
        self,
        definition: StageDefinition,
        instance: SubmissionInstance,
        upstream: Mapping[str, StoredStageResult],
    ) -> str:
        return fingerprint_value(
            {
                "submission_id": self.submission_id,
                "instance_id": instance.instance_id,
                "model_patch": instance.model_patch,
                "stage": definition.name,
                "implementation_version": definition.implementation_version,
                "semantic_config": dict(definition.semantic_inputs(self.config)),
                "resources": dict(definition.resource_inputs(self.config)),
                "upstream": {
                    name: fingerprint_value(result.model_dump(mode="json"))
                    for name, result in sorted(upstream.items())
                },
            }
        )

    def _execution_fingerprint(self, definition: StageDefinition) -> str:
        return fingerprint_value(
            {
                "stage": definition.name,
                "implementation_version": definition.implementation_version,
                "max_attempts": self.max_attempts,
                "execution_config": dict(
                    definition.execution_inputs(self.config)
                ),
            }
        )

    def _invalidate(
        self,
        stage_name: str,
        instance_id: str,
        reason: str,
    ) -> None:
        self.workspace.mark_stale(
            self.registry.downstream(stage_name),
            instance_id,
            reason,
        )
