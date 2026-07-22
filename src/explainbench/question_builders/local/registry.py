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
from explainbench.question_builders.local.runners import (
    FindFirstDivergenceRunner,
    IdentifyPatchedFunctionsRunner,
    SelectTraceFunctionsRunner,
    TraceProgramStateRunner,
    TrackTestCallsRunner,
)


class UnconnectedStageRunner:
    """Explicit placeholder until a canonical stage command is connected."""

    def __init__(self, stage_name: str) -> None:
        self.stage_name = stage_name

    def run_instance(self, context: StageContext):
        raise StageExecutionError(
            f"stage {self.stage_name!r} is not yet connected to its "
            "canonical command",
            category="stage_not_connected",
            retryable=False,
        )

    def validate_result(self, result: StoredStageResult) -> None:
        if not isinstance(result.data, dict):
            raise ValueError("stage result data must be an object")


def _candidate_model(config: LocalBuilderConfig) -> dict[str, str]:
    return {"candidate_generation_model": config.candidate_generation_model}


def _identify_resources(config: LocalBuilderConfig) -> dict[str, str]:
    return {"dataset_name": config.dataset_name}


def _identify_execution(config: LocalBuilderConfig) -> dict[str, str | int]:
    return {
        "repository_cache": str(
            config.repository_cache or config.workspace / "repositories"
        ),
        "repository_remote": config.repository_remote,
        "timeout_seconds": config.identify_timeout_seconds,
    }


def _track_execution(config: LocalBuilderConfig) -> dict[str, str | int | bool]:
    return {
        "test_timeout_seconds": config.track_test_timeout_seconds,
        "command_timeout_seconds": config.track_command_timeout_seconds,
        "harness_workers": 1,
        "cache_level": "env",
        "force_rebuild": False,
        "clean": False,
        "open_file_limit": 4096,
        "namespace": "swebench",
        "instance_image_tag": "latest",
        "env_image_tag": "latest",
    }


def _select_trace_execution(config: LocalBuilderConfig) -> dict[str, int]:
    return {"timeout_seconds": config.select_trace_timeout_seconds}


def _trace_execution(config: LocalBuilderConfig) -> dict[str, str | int | bool]:
    return {
        "test_timeout_seconds": config.trace_test_timeout_seconds,
        "command_timeout_seconds": config.trace_command_timeout_seconds,
        "harness_workers": 1,
        "cache_level": "env",
        "force_rebuild": False,
        "clean": False,
        "open_file_limit": 4096,
        "namespace": "swebench",
        "instance_image_tag": "latest",
        "env_image_tag": "latest",
    }


def _divergence_semantic(config: LocalBuilderConfig) -> dict[str, int | bool]:
    return {
        "depth_threshold": config.divergence_depth_threshold,
        "simplify": config.divergence_simplify,
        "variable_max_depth": config.divergence_variable_max_depth,
        "parameter_max_depth": config.divergence_parameter_max_depth,
    }


def _divergence_execution(config: LocalBuilderConfig) -> dict[str, int]:
    return {
        "timeout_seconds": config.divergence_timeout_seconds,
        "command_timeout_seconds": config.divergence_command_timeout_seconds,
        "instance_workers": config.divergence_instance_workers,
        "agent_workers": config.divergence_agent_workers,
    }


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
        runner=UnconnectedStageRunner(name),
        **({} if semantic_inputs is None else {"semantic_inputs": semantic_inputs}),
    )


LOCAL_STAGE_REGISTRY = StageRegistry(
    [
        StageDefinition(
            name="identify-patched-functions",
            description="find Python functions changed by the submitted patch",
            dependencies=(),
            implementation_version="1-canonical-cli",
            runner=IdentifyPatchedFunctionsRunner(),
            resource_inputs=_identify_resources,
            execution_inputs=_identify_execution,
        ),
        StageDefinition(
            name="track-test-calls",
            description="run relevant tests with lightweight call tracking",
            dependencies=("identify-patched-functions",),
            implementation_version="1-canonical-cli",
            runner=TrackTestCallsRunner(),
            resource_inputs=_identify_resources,
            execution_inputs=_track_execution,
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
            implementation_version="1-canonical-cli",
            runner=SelectTraceFunctionsRunner(),
            execution_inputs=_select_trace_execution,
        ),
        StageDefinition(
            name="trace-program-state",
            description="record detailed buggy and patched program state",
            dependencies=("select-trace-functions",),
            implementation_version="1-canonical-cli",
            runner=TraceProgramStateRunner(),
            resource_inputs=_identify_resources,
            execution_inputs=_trace_execution,
        ),
        StageDefinition(
            name="find-first-divergence",
            description="locate the first useful state or control-flow difference",
            dependencies=("trace-program-state",),
            implementation_version="1-canonical-cli",
            runner=FindFirstDivergenceRunner(),
            semantic_inputs=_divergence_semantic,
            execution_inputs=_divergence_execution,
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
