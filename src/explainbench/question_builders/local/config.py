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
DEFAULT_DATASET_NAME = "SWE-bench/SWE-bench_Verified"
DEFAULT_REPOSITORY_REMOTE = "https://github.com"
DEFAULT_IDENTIFY_TIMEOUT_SECONDS = 3600
DEFAULT_TRACK_TEST_TIMEOUT_SECONDS = 1800
DEFAULT_TRACK_COMMAND_TIMEOUT_SECONDS = 4500


class LocalBuilderConfigError(ValueError):
    """Raised when local question-builder configuration is invalid."""


class ExecutionFileConfig(StrictModel):
    workers: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1)
    identify_timeout_seconds: int | None = Field(default=None, ge=1)
    track_test_timeout_seconds: int | None = Field(default=None, ge=1)
    track_command_timeout_seconds: int | None = Field(default=None, ge=1)


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

    @field_validator("workspace", "output", "repository_cache")
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
    source: Path | None = None


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
    repository_cache: str | Path | None = None,
    dataset_name: str | None = None,
    repository_remote: str | None = None,
    identify_timeout_seconds: int | None = None,
    track_test_timeout_seconds: int | None = None,
    track_command_timeout_seconds: int | None = None,
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

    return LocalBuilderConfig(
        workspace=workspace_path,
        artifact_output=output_path,
        max_workers=resolved_workers,
        max_attempts=resolved_attempts,
        candidate_generation_model=model,
        repository_cache=repository_cache_path,
        dataset_name=resolved_dataset_name,
        repository_remote=resolved_repository_remote,
        identify_timeout_seconds=resolved_identify_timeout,
        track_test_timeout_seconds=resolved_track_test_timeout,
        track_command_timeout_seconds=resolved_track_command_timeout,
        source=source,
    )
