"""Versioned configuration for local-effect question construction."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from explainbench.schemas import StrictModel


DEFAULT_WORKERS = 1
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_CANDIDATE_GENERATION_MODEL = "gpt-5.2-2025-12-11"
DEFAULT_CANDIDATE_GENERATION_CHANGED_CANDIDATES = 10
DEFAULT_CANDIDATE_GENERATION_UNCHANGED_CANDIDATES = 10
DEFAULT_CANDIDATE_GENERATION_INFERENCE = True
DEFAULT_CANDIDATE_GENERATION_INSTANCE_WORKERS = 1
DEFAULT_CANDIDATE_GENERATION_AGENT_WORKERS = 1
DEFAULT_CANDIDATE_GENERATION_REASONING_EFFORT = "medium"
DEFAULT_CANDIDATE_GENERATION_MODEL_RETRIES = 5
DEFAULT_CANDIDATE_GENERATION_COMMAND_TIMEOUT_SECONDS = 3600
DEFAULT_DATASET_NAME = "SWE-bench/SWE-bench_Verified"
DEFAULT_REPOSITORY_REMOTE = "https://github.com"
DEFAULT_IDENTIFY_TIMEOUT_SECONDS = 3600
DEFAULT_TRACK_TEST_TIMEOUT_SECONDS = 1800
DEFAULT_TRACK_COMMAND_TIMEOUT_SECONDS = 4500
DEFAULT_SELECT_TRACE_TIMEOUT_SECONDS = 1800
DEFAULT_TRACE_TEST_TIMEOUT_SECONDS = 21600
DEFAULT_TRACE_COMMAND_TIMEOUT_SECONDS = 45000
DEFAULT_DIVERGENCE_DEPTH_THRESHOLD = 3
DEFAULT_DIVERGENCE_TIMEOUT_SECONDS = 600
DEFAULT_DIVERGENCE_COMMAND_TIMEOUT_SECONDS = 3600
DEFAULT_DIVERGENCE_INSTANCE_WORKERS = 1
DEFAULT_DIVERGENCE_AGENT_WORKERS = 1
DEFAULT_DIVERGENCE_SIMPLIFY = True
DEFAULT_DIVERGENCE_VARIABLE_MAX_DEPTH = 4
DEFAULT_DIVERGENCE_PARAMETER_MAX_DEPTH = 3
_CANDIDATE_REASONING_EFFORTS = frozenset(
    {"minimal", "low", "medium", "high"}
)


class LocalBuilderConfigError(ValueError):
    """Raised when local question-builder configuration is invalid."""


class ExecutionFileConfig(StrictModel):
    workers: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1)
    identify_timeout_seconds: int | None = Field(default=None, ge=1)
    track_test_timeout_seconds: int | None = Field(default=None, ge=1)
    track_command_timeout_seconds: int | None = Field(default=None, ge=1)
    select_trace_timeout_seconds: int | None = Field(default=None, ge=1)
    trace_test_timeout_seconds: int | None = Field(default=None, ge=1)
    trace_command_timeout_seconds: int | None = Field(default=None, ge=1)
    divergence_depth_threshold: int | None = Field(default=None, ge=0)
    divergence_timeout_seconds: int | None = Field(default=None, ge=1)
    divergence_command_timeout_seconds: int | None = Field(default=None, ge=1)
    divergence_instance_workers: int | None = Field(default=None, ge=1)
    divergence_agent_workers: int | None = Field(default=None, ge=1)
    divergence_simplify: bool | None = None
    divergence_variable_max_depth: int | None = Field(default=None, ge=0)
    divergence_parameter_max_depth: int | None = Field(default=None, ge=0)
    candidate_generation_changed_candidates: int | None = Field(
        default=None, ge=1
    )
    candidate_generation_unchanged_candidates: int | None = Field(
        default=None, ge=1
    )
    candidate_generation_inference: bool | None = None
    candidate_generation_instance_workers: int | None = Field(
        default=None, ge=1
    )
    candidate_generation_agent_workers: int | None = Field(default=None, ge=1)
    candidate_generation_model_retries: int | None = Field(default=None, ge=1)
    candidate_generation_command_timeout_seconds: int | None = Field(
        default=None, ge=1
    )
    candidate_generation_reasoning_effort: str | None = None


class ModelsFileConfig(StrictModel):
    candidate_generation: str | None = None

    @field_validator("candidate_generation")
    @classmethod
    def reject_blank_model(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must be a nonempty string")
        return value


class PathsFileConfig(StrictModel):
    workspace: str | None = None
    output: str | None = None
    repository_cache: str | None = None
    candidate_generation_env_file: str | None = None

    @field_validator(
        "workspace",
        "output",
        "repository_cache",
        "candidate_generation_env_file",
    )
    @classmethod
    def reject_blank_path(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must be a nonempty path")
        return value


class BenchmarkFileConfig(StrictModel):
    dataset_name: str | None = None
    repository_remote: str | None = None

    @field_validator("dataset_name", "repository_remote")
    @classmethod
    def reject_blank_value(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must be a nonempty string")
        return value


class LocalBuilderFileConfig(StrictModel):
    schema_version: Literal[1]
    execution: ExecutionFileConfig = Field(default_factory=ExecutionFileConfig)
    models: ModelsFileConfig = Field(default_factory=ModelsFileConfig)
    paths: PathsFileConfig = Field(default_factory=PathsFileConfig)
    benchmark: BenchmarkFileConfig = Field(default_factory=BenchmarkFileConfig)


@dataclass(frozen=True)
class LocalBuilderConfig:
    """Fully resolved settings used by local stage implementations."""

    workspace: Path
    artifact_output: Path | None
    max_workers: int
    max_attempts: int
    candidate_generation_model: str
    repository_cache: Path | None = None
    dataset_name: str = DEFAULT_DATASET_NAME
    repository_remote: str = DEFAULT_REPOSITORY_REMOTE
    identify_timeout_seconds: int = DEFAULT_IDENTIFY_TIMEOUT_SECONDS
    track_test_timeout_seconds: int = DEFAULT_TRACK_TEST_TIMEOUT_SECONDS
    track_command_timeout_seconds: int = DEFAULT_TRACK_COMMAND_TIMEOUT_SECONDS
    select_trace_timeout_seconds: int = DEFAULT_SELECT_TRACE_TIMEOUT_SECONDS
    trace_test_timeout_seconds: int = DEFAULT_TRACE_TEST_TIMEOUT_SECONDS
    trace_command_timeout_seconds: int = DEFAULT_TRACE_COMMAND_TIMEOUT_SECONDS
    divergence_depth_threshold: int = DEFAULT_DIVERGENCE_DEPTH_THRESHOLD
    divergence_timeout_seconds: int = DEFAULT_DIVERGENCE_TIMEOUT_SECONDS
    divergence_command_timeout_seconds: int = (
        DEFAULT_DIVERGENCE_COMMAND_TIMEOUT_SECONDS
    )
    divergence_instance_workers: int = DEFAULT_DIVERGENCE_INSTANCE_WORKERS
    divergence_agent_workers: int = DEFAULT_DIVERGENCE_AGENT_WORKERS
    divergence_simplify: bool = DEFAULT_DIVERGENCE_SIMPLIFY
    divergence_variable_max_depth: int = DEFAULT_DIVERGENCE_VARIABLE_MAX_DEPTH
    divergence_parameter_max_depth: int = DEFAULT_DIVERGENCE_PARAMETER_MAX_DEPTH
    source: Path | None = None
    candidate_generation_changed_candidates: int = (
        DEFAULT_CANDIDATE_GENERATION_CHANGED_CANDIDATES
    )
    candidate_generation_unchanged_candidates: int = (
        DEFAULT_CANDIDATE_GENERATION_UNCHANGED_CANDIDATES
    )
    candidate_generation_inference: bool = DEFAULT_CANDIDATE_GENERATION_INFERENCE
    candidate_generation_instance_workers: int = (
        DEFAULT_CANDIDATE_GENERATION_INSTANCE_WORKERS
    )
    candidate_generation_agent_workers: int = (
        DEFAULT_CANDIDATE_GENERATION_AGENT_WORKERS
    )
    candidate_generation_reasoning_effort: str = (
        DEFAULT_CANDIDATE_GENERATION_REASONING_EFFORT
    )
    candidate_generation_model_retries: int = (
        DEFAULT_CANDIDATE_GENERATION_MODEL_RETRIES
    )
    candidate_generation_command_timeout_seconds: int = (
        DEFAULT_CANDIDATE_GENERATION_COMMAND_TIMEOUT_SECONDS
    )
    candidate_generation_env_file: Path | None = None


def _validation_message(error: ValidationError) -> str:
    detail = error.errors(include_url=False, include_context=False)[0]
    location = ".".join(str(part) for part in detail["loc"])
    message = detail["msg"]
    if message.startswith("Value error, "):
        message = message.removeprefix("Value error, ")
    return f"{location}: {message}" if location else message


def load_local_builder_config(
    path: str | Path,
) -> tuple[LocalBuilderFileConfig, Path]:
    """Load and strictly validate a local-builder TOML file."""

    source = Path(path).expanduser().resolve()
    try:
        with source.open("rb") as config_file:
            payload = tomllib.load(config_file)
    except OSError as error:
        raise LocalBuilderConfigError(
            f"cannot read local-builder config {source}: "
            f"{error.strerror or error}"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise LocalBuilderConfigError(
            f"local-builder config {source} is not valid TOML: {error}"
        ) from error
    try:
        return LocalBuilderFileConfig.model_validate(payload), source
    except ValidationError as error:
        raise LocalBuilderConfigError(
            f"invalid local-builder config {source}: "
            f"{_validation_message(error)}"
        ) from error


def _pick(cli_value, file_value, default=None):
    if cli_value is not None:
        return cli_value
    if file_value is not None:
        return file_value
    return default


def _config_path(value: str | None, source: Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and source is not None:
        path = source.parent / path
    return path.resolve()


def resolve_local_builder_config(
    config: LocalBuilderFileConfig | None = None,
    *,
    source: Path | None = None,
    workspace: str | Path | None = None,
    output: str | Path | None = None,
    workers: int | None = None,
    max_attempts: int | None = None,
    candidate_generation_model: str | None = None,
    candidate_generation_changed_candidates: int | None = None,
    candidate_generation_unchanged_candidates: int | None = None,
    candidate_generation_inference: bool | None = None,
    candidate_generation_instance_workers: int | None = None,
    candidate_generation_agent_workers: int | None = None,
    candidate_generation_reasoning_effort: str | None = None,
    candidate_generation_model_retries: int | None = None,
    candidate_generation_command_timeout_seconds: int | None = None,
    candidate_generation_env_file: str | Path | None = None,
    repository_cache: str | Path | None = None,
    dataset_name: str | None = None,
    repository_remote: str | None = None,
    identify_timeout_seconds: int | None = None,
    track_test_timeout_seconds: int | None = None,
    track_command_timeout_seconds: int | None = None,
    select_trace_timeout_seconds: int | None = None,
    trace_test_timeout_seconds: int | None = None,
    trace_command_timeout_seconds: int | None = None,
    divergence_depth_threshold: int | None = None,
    divergence_timeout_seconds: int | None = None,
    divergence_command_timeout_seconds: int | None = None,
    divergence_instance_workers: int | None = None,
    divergence_agent_workers: int | None = None,
    divergence_simplify: bool | None = None,
    divergence_variable_max_depth: int | None = None,
    divergence_parameter_max_depth: int | None = None,
    require_output: bool = False,
) -> LocalBuilderConfig:
    """Merge command-line overrides over config values and safe defaults."""

    file_config = config or LocalBuilderFileConfig(schema_version=1)
    if workspace is not None:
        workspace_path = Path(workspace).expanduser()
    else:
        workspace_path = _config_path(file_config.paths.workspace, source)
    if workspace_path is None:
        raise LocalBuilderConfigError(
            "a workspace is required via --workspace or paths.workspace"
        )

    if output is not None:
        output_path = Path(output).expanduser()
    else:
        output_path = _config_path(file_config.paths.output, source)
    if require_output and output_path is None:
        raise LocalBuilderConfigError(
            "an artifact output directory is required via --output or paths.output"
        )

    if repository_cache is not None:
        repository_cache_path = Path(repository_cache).expanduser()
    else:
        repository_cache_path = _config_path(
            file_config.paths.repository_cache,
            source,
        )
    if repository_cache_path is None:
        repository_cache_path = workspace_path / "repositories"

    if candidate_generation_env_file is not None:
        candidate_generation_env_path = (
            Path(candidate_generation_env_file).expanduser().resolve()
        )
    else:
        candidate_generation_env_path = _config_path(
            file_config.paths.candidate_generation_env_file,
            source,
        )

    try:
        resolved_workers = int(
            _pick(workers, file_config.execution.workers, DEFAULT_WORKERS)
        )
        resolved_attempts = int(
            _pick(
                max_attempts,
                file_config.execution.max_attempts,
                DEFAULT_MAX_ATTEMPTS,
            )
        )
        model = _pick(
            candidate_generation_model,
            file_config.models.candidate_generation,
            DEFAULT_CANDIDATE_GENERATION_MODEL,
        )
        resolved_candidate_changed = int(
            _pick(
                candidate_generation_changed_candidates,
                file_config.execution.candidate_generation_changed_candidates,
                DEFAULT_CANDIDATE_GENERATION_CHANGED_CANDIDATES,
            )
        )
        resolved_candidate_unchanged = int(
            _pick(
                candidate_generation_unchanged_candidates,
                file_config.execution.candidate_generation_unchanged_candidates,
                DEFAULT_CANDIDATE_GENERATION_UNCHANGED_CANDIDATES,
            )
        )
        resolved_candidate_inference = bool(
            _pick(
                candidate_generation_inference,
                file_config.execution.candidate_generation_inference,
                DEFAULT_CANDIDATE_GENERATION_INFERENCE,
            )
        )
        resolved_candidate_instance_workers = int(
            _pick(
                candidate_generation_instance_workers,
                file_config.execution.candidate_generation_instance_workers,
                DEFAULT_CANDIDATE_GENERATION_INSTANCE_WORKERS,
            )
        )
        resolved_candidate_agent_workers = int(
            _pick(
                candidate_generation_agent_workers,
                file_config.execution.candidate_generation_agent_workers,
                DEFAULT_CANDIDATE_GENERATION_AGENT_WORKERS,
            )
        )
        resolved_candidate_reasoning = _pick(
            candidate_generation_reasoning_effort,
            file_config.execution.candidate_generation_reasoning_effort,
            DEFAULT_CANDIDATE_GENERATION_REASONING_EFFORT,
        )
        resolved_candidate_retries = int(
            _pick(
                candidate_generation_model_retries,
                file_config.execution.candidate_generation_model_retries,
                DEFAULT_CANDIDATE_GENERATION_MODEL_RETRIES,
            )
        )
        resolved_candidate_command_timeout = int(
            _pick(
                candidate_generation_command_timeout_seconds,
                file_config.execution.candidate_generation_command_timeout_seconds,
                DEFAULT_CANDIDATE_GENERATION_COMMAND_TIMEOUT_SECONDS,
            )
        )
        resolved_dataset_name = _pick(
            dataset_name,
            file_config.benchmark.dataset_name,
            DEFAULT_DATASET_NAME,
        )
        resolved_repository_remote = _pick(
            repository_remote,
            file_config.benchmark.repository_remote,
            DEFAULT_REPOSITORY_REMOTE,
        )
        resolved_identify_timeout = int(
            _pick(
                identify_timeout_seconds,
                file_config.execution.identify_timeout_seconds,
                DEFAULT_IDENTIFY_TIMEOUT_SECONDS,
            )
        )
        resolved_track_test_timeout = int(
            _pick(
                track_test_timeout_seconds,
                file_config.execution.track_test_timeout_seconds,
                DEFAULT_TRACK_TEST_TIMEOUT_SECONDS,
            )
        )
        resolved_track_command_timeout = int(
            _pick(
                track_command_timeout_seconds,
                file_config.execution.track_command_timeout_seconds,
                DEFAULT_TRACK_COMMAND_TIMEOUT_SECONDS,
            )
        )
        resolved_select_trace_timeout = int(
            _pick(
                select_trace_timeout_seconds,
                file_config.execution.select_trace_timeout_seconds,
                DEFAULT_SELECT_TRACE_TIMEOUT_SECONDS,
            )
        )
        resolved_trace_test_timeout = int(
            _pick(
                trace_test_timeout_seconds,
                file_config.execution.trace_test_timeout_seconds,
                DEFAULT_TRACE_TEST_TIMEOUT_SECONDS,
            )
        )
        resolved_trace_command_timeout = int(
            _pick(
                trace_command_timeout_seconds,
                file_config.execution.trace_command_timeout_seconds,
                DEFAULT_TRACE_COMMAND_TIMEOUT_SECONDS,
            )
        )
        resolved_divergence_depth_threshold = int(
            _pick(
                divergence_depth_threshold,
                file_config.execution.divergence_depth_threshold,
                DEFAULT_DIVERGENCE_DEPTH_THRESHOLD,
            )
        )
        resolved_divergence_timeout = int(
            _pick(
                divergence_timeout_seconds,
                file_config.execution.divergence_timeout_seconds,
                DEFAULT_DIVERGENCE_TIMEOUT_SECONDS,
            )
        )
        resolved_divergence_command_timeout = int(
            _pick(
                divergence_command_timeout_seconds,
                file_config.execution.divergence_command_timeout_seconds,
                DEFAULT_DIVERGENCE_COMMAND_TIMEOUT_SECONDS,
            )
        )
        resolved_divergence_instance_workers = int(
            _pick(
                divergence_instance_workers,
                file_config.execution.divergence_instance_workers,
                DEFAULT_DIVERGENCE_INSTANCE_WORKERS,
            )
        )
        resolved_divergence_agent_workers = int(
            _pick(
                divergence_agent_workers,
                file_config.execution.divergence_agent_workers,
                DEFAULT_DIVERGENCE_AGENT_WORKERS,
            )
        )
        resolved_divergence_simplify = bool(
            _pick(
                divergence_simplify,
                file_config.execution.divergence_simplify,
                DEFAULT_DIVERGENCE_SIMPLIFY,
            )
        )
        resolved_divergence_variable_max_depth = int(
            _pick(
                divergence_variable_max_depth,
                file_config.execution.divergence_variable_max_depth,
                DEFAULT_DIVERGENCE_VARIABLE_MAX_DEPTH,
            )
        )
        resolved_divergence_parameter_max_depth = int(
            _pick(
                divergence_parameter_max_depth,
                file_config.execution.divergence_parameter_max_depth,
                DEFAULT_DIVERGENCE_PARAMETER_MAX_DEPTH,
            )
        )
    except (TypeError, ValueError) as error:
        raise LocalBuilderConfigError(str(error)) from error
    if resolved_workers < 1:
        raise LocalBuilderConfigError("workers must be at least 1")
    if resolved_attempts < 1:
        raise LocalBuilderConfigError("max attempts must be at least 1")
    if not isinstance(model, str) or not model.strip():
        raise LocalBuilderConfigError(
            "candidate generation model must be a nonempty string"
        )
    if resolved_candidate_changed < 1:
        raise LocalBuilderConfigError(
            "candidate changed count must be at least 1"
        )
    if resolved_candidate_unchanged < 1:
        raise LocalBuilderConfigError(
            "candidate unchanged count must be at least 1"
        )
    if resolved_candidate_instance_workers < 1:
        raise LocalBuilderConfigError(
            "candidate instance workers must be at least 1"
        )
    if resolved_candidate_agent_workers < 1:
        raise LocalBuilderConfigError(
            "candidate agent workers must be at least 1"
        )
    if resolved_candidate_reasoning not in _CANDIDATE_REASONING_EFFORTS:
        raise LocalBuilderConfigError(
            "candidate reasoning effort must be one of: "
            + ", ".join(sorted(_CANDIDATE_REASONING_EFFORTS))
        )
    if resolved_candidate_retries < 1:
        raise LocalBuilderConfigError(
            "candidate model retries must be at least 1"
        )
    if resolved_candidate_command_timeout < 1:
        raise LocalBuilderConfigError(
            "candidate command timeout must be at least 1 second"
        )
    if (
        not isinstance(resolved_dataset_name, str)
        or not resolved_dataset_name.strip()
    ):
        raise LocalBuilderConfigError("dataset name must be a nonempty string")
    if (
        not isinstance(resolved_repository_remote, str)
        or not resolved_repository_remote.strip()
    ):
        raise LocalBuilderConfigError(
            "repository remote must be a nonempty string"
        )
    if resolved_identify_timeout < 1:
        raise LocalBuilderConfigError(
            "identify timeout must be at least 1 second"
        )
    if resolved_track_test_timeout < 1:
        raise LocalBuilderConfigError(
            "track test timeout must be at least 1 second"
        )
    if resolved_track_command_timeout < 1:
        raise LocalBuilderConfigError(
            "track command timeout must be at least 1 second"
        )
    if resolved_select_trace_timeout < 1:
        raise LocalBuilderConfigError(
            "select trace timeout must be at least 1 second"
        )
    if resolved_trace_test_timeout < 1:
        raise LocalBuilderConfigError(
            "trace test timeout must be at least 1 second"
        )
    if resolved_trace_command_timeout < 1:
        raise LocalBuilderConfigError(
            "trace command timeout must be at least 1 second"
        )
    if resolved_divergence_depth_threshold < 0:
        raise LocalBuilderConfigError(
            "divergence depth threshold must be nonnegative"
        )
    if resolved_divergence_timeout < 1:
        raise LocalBuilderConfigError(
            "divergence timeout must be at least 1 second"
        )
    if resolved_divergence_command_timeout < 1:
        raise LocalBuilderConfigError(
            "divergence command timeout must be at least 1 second"
        )
    if resolved_divergence_instance_workers < 1:
        raise LocalBuilderConfigError(
            "divergence instance workers must be at least 1"
        )
    if resolved_divergence_agent_workers < 1:
        raise LocalBuilderConfigError(
            "divergence agent workers must be at least 1"
        )
    if resolved_divergence_variable_max_depth < 0:
        raise LocalBuilderConfigError(
            "divergence variable max depth must be nonnegative"
        )
    if resolved_divergence_parameter_max_depth < 0:
        raise LocalBuilderConfigError(
            "divergence parameter max depth must be nonnegative"
        )

    return LocalBuilderConfig(
        workspace=workspace_path,
        artifact_output=output_path,
        max_workers=resolved_workers,
        max_attempts=resolved_attempts,
        candidate_generation_model=model,
        candidate_generation_changed_candidates=resolved_candidate_changed,
        candidate_generation_unchanged_candidates=resolved_candidate_unchanged,
        candidate_generation_inference=resolved_candidate_inference,
        candidate_generation_instance_workers=resolved_candidate_instance_workers,
        candidate_generation_agent_workers=resolved_candidate_agent_workers,
        candidate_generation_reasoning_effort=resolved_candidate_reasoning,
        candidate_generation_model_retries=resolved_candidate_retries,
        candidate_generation_command_timeout_seconds=(
            resolved_candidate_command_timeout
        ),
        candidate_generation_env_file=candidate_generation_env_path,
        repository_cache=repository_cache_path,
        dataset_name=resolved_dataset_name,
        repository_remote=resolved_repository_remote,
        identify_timeout_seconds=resolved_identify_timeout,
        track_test_timeout_seconds=resolved_track_test_timeout,
        track_command_timeout_seconds=resolved_track_command_timeout,
        select_trace_timeout_seconds=resolved_select_trace_timeout,
        trace_test_timeout_seconds=resolved_trace_test_timeout,
        trace_command_timeout_seconds=resolved_trace_command_timeout,
        divergence_depth_threshold=resolved_divergence_depth_threshold,
        divergence_timeout_seconds=resolved_divergence_timeout,
        divergence_command_timeout_seconds=resolved_divergence_command_timeout,
        divergence_instance_workers=resolved_divergence_instance_workers,
        divergence_agent_workers=resolved_divergence_agent_workers,
        divergence_simplify=resolved_divergence_simplify,
        divergence_variable_max_depth=resolved_divergence_variable_max_depth,
        divergence_parameter_max_depth=resolved_divergence_parameter_max_depth,
        source=source,
    )
