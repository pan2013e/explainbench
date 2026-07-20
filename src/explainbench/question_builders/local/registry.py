"""Named stage registry for the local-effect question-builder pipeline."""

from __future__ import annotations

from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageDefinition,
    StageExecutionError,
    StageRegistry,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.question_builders.local.config import LocalBuilderConfig


class PendingMigrationRunner:
    """Explicit placeholder until a scientific stage is migrated."""

    def __init__(self, stage_name: str) -> None:
        self.stage_name = stage_name

    def run_instance(self, context: StageContext):
        raise StageExecutionError(
            f"stage {self.stage_name!r} has not yet been migrated from the "
            "research pipeline",
            category="stage_not_migrated",
            retryable=False,
        )

    def validate_result(self, result: StoredStageResult) -> None:
        if not isinstance(result.data, dict):
            raise ValueError("stage result data must be an object")


def _candidate_model(config: LocalBuilderConfig) -> dict[str, str]:
    return {"candidate_generation_model": config.candidate_generation_model}


def _stage(
    name: str,
    description: str,
    dependency: str | None,
    *,
    semantic_inputs=None,
) -> StageDefinition:
    return StageDefinition(
        name=name,
        description=description,
        dependencies=() if dependency is None else (dependency,),
        implementation_version="0-pending-migration",
        runner=PendingMigrationRunner(name),
        **({} if semantic_inputs is None else {"semantic_inputs": semantic_inputs}),
    )


LOCAL_STAGE_REGISTRY = StageRegistry(
    [
        _stage(
            "identify-patched-functions",
            "find Python functions changed by the submitted patch",
            None,
        ),
        _stage(
            "track-test-calls",
            "run relevant tests with lightweight call tracking",
            "identify-patched-functions",
        ),
        _stage(
            "select-trace-functions",
            "select functions for detailed tracing from observed call paths",
            "track-test-calls",
        ),
        _stage(
            "trace-program-state",
            "record detailed buggy and patched program state",
            "select-trace-functions",
        ),
        _stage(
            "find-first-divergence",
            "locate the first useful state or control-flow difference",
            "trace-program-state",
        ),
        _stage(
            "generate-candidate-expressions",
            "generate expressions that may or may not change",
            "find-first-divergence",
            semantic_inputs=_candidate_model,
        ),
        _stage(
            "execute-candidate-expressions",
            "evaluate candidate expressions in buggy and patched executions",
            "generate-candidate-expressions",
        ),
        _stage(
            "validate-candidate-expressions",
            "classify candidate expressions from their recorded values",
            "execute-candidate-expressions",
        ),
        _stage(
            "build-answer-choices",
            "select and shuffle the final answer choices",
            "validate-candidate-expressions",
        ),
        _stage(
            "export-question-artifacts",
            "write evaluator-compatible context and ground truth artifacts",
            "build-answer-choices",
        ),
    ]
)

