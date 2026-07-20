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
from explainbench.question_builders.local.stages.identify_patched_functions import (
    IdentifyPatchedFunctionsRunner,
)
from explainbench.question_builders.local.stages.select_trace_functions import (
    SelectTraceFunctionsRunner,
)
from explainbench.question_builders.local.stages.validate_candidate_expressions import (
    ValidateCandidateExpressionsRunner,
)
from explainbench.question_builders.local.stages.build_answer_choices import (
    BuildAnswerChoicesRunner,
)
from explainbench.question_builders.local.stages.export_question_artifacts import (
    ExportQuestionArtifactsRunner,
)
from explainbench.question_builders.local.stages.find_first_divergence import (
    FindFirstDivergenceRunner,
)


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


def _benchmark_source(config: LocalBuilderConfig) -> dict[str, str]:
    return {
        "benchmark_dataset": config.benchmark_dataset,
        "benchmark_split": config.benchmark_split,
        "repository_remote": config.repository_remote,
    }


def _choice_settings(config: LocalBuilderConfig) -> dict[str, int | float]:
    return {
        "correct_choices": config.correct_choices,
        "incorrect_choices": config.incorrect_choices,
        "mmr_weight": config.mmr_weight,
        "random_seed": config.random_seed,
    }


def _divergence_settings(config: LocalBuilderConfig) -> dict[str, int]:
    return {
        "divergence_depth": config.divergence_depth,
        "variable_max_depth": config.variable_max_depth,
        "parameter_max_depth": config.parameter_max_depth,
        "random_seed": config.random_seed,
    }


def _stage(
    name: str,
    description: str,
    dependency: str | tuple[str, ...] | None,
    *,
    semantic_inputs=None,
) -> StageDefinition:
    return StageDefinition(
        name=name,
        description=description,
        dependencies=(
            ()
            if dependency is None
            else dependency
            if isinstance(dependency, tuple)
            else (dependency,)
        ),
        implementation_version="0-pending-migration",
        runner=PendingMigrationRunner(name),
        **({} if semantic_inputs is None else {"semantic_inputs": semantic_inputs}),
    )


LOCAL_STAGE_REGISTRY = StageRegistry(
    [
        StageDefinition(
            name="identify-patched-functions",
            description="find Python functions changed by the submitted patch",
            dependencies=(),
            implementation_version="1",
            runner=IdentifyPatchedFunctionsRunner(),
            semantic_inputs=_benchmark_source,
        ),
        _stage(
            "track-test-calls",
            "run relevant tests with lightweight call tracking",
            "identify-patched-functions",
        ),
        StageDefinition(
            name="select-trace-functions",
            description=(
                "select functions for detailed tracing from observed call paths"
            ),
            dependencies=(
                "identify-patched-functions",
                "track-test-calls",
            ),
            implementation_version="1",
            runner=SelectTraceFunctionsRunner(),
        ),
        _stage(
            "trace-program-state",
            "record detailed buggy and patched program state",
            "select-trace-functions",
        ),
        StageDefinition(
            name="find-first-divergence",
            description=(
                "locate the first useful state or control-flow difference"
            ),
            dependencies=("trace-program-state",),
            implementation_version="1",
            runner=FindFirstDivergenceRunner(),
            semantic_inputs=_divergence_settings,
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
        StageDefinition(
            name="validate-candidate-expressions",
            description=(
                "classify candidate expressions from their recorded values"
            ),
            dependencies=("execute-candidate-expressions",),
            implementation_version="1",
            runner=ValidateCandidateExpressionsRunner(),
        ),
        StageDefinition(
            name="build-answer-choices",
            description="select and shuffle the final answer choices",
            dependencies=("validate-candidate-expressions",),
            implementation_version="1",
            runner=BuildAnswerChoicesRunner(),
            semantic_inputs=_choice_settings,
        ),
        StageDefinition(
            name="export-question-artifacts",
            description=(
                "write evaluator-compatible context and ground truth artifacts"
            ),
            dependencies=("build-answer-choices",),
            implementation_version="1",
            runner=ExportQuestionArtifactsRunner(),
        ),
    ]
)
