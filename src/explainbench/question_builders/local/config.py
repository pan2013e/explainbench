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
DEFAULT_BENCHMARK_DATASET = "SWE-bench/SWE-bench_Verified"
DEFAULT_BENCHMARK_SPLIT = "test"
DEFAULT_REPOSITORY_REMOTE = "https://github.com"
DEFAULT_DIVERGENCE_DEPTH = 3
DEFAULT_VARIABLE_MAX_DEPTH = 4
DEFAULT_PARAMETER_MAX_DEPTH = 3
DEFAULT_CORRECT_CHOICES = 1
DEFAULT_INCORRECT_CHOICES = 3
DEFAULT_MMR_WEIGHT = 0.7
DEFAULT_RANDOM_SEED = 42


class LocalBuilderConfigError(ValueError):
    """Raised when local question-builder configuration is invalid."""


class ExecutionFileConfig(StrictModel):
    workers: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1)


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

    @field_validator("workspace", "output")
    @classmethod
    def reject_blank_path(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must be a nonempty path")
        return value


class BenchmarkFileConfig(StrictModel):
    dataset: str | None = None
    split: str | None = None
    repository_remote: str | None = None

    @field_validator("dataset", "split", "repository_remote")
    @classmethod
    def reject_blank_value(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must be a nonempty string")
        return value


class DivergenceFileConfig(StrictModel):
    depth: int | None = Field(default=None, ge=0)
    variable_max_depth: int | None = Field(default=None, ge=0)
    parameter_max_depth: int | None = Field(default=None, ge=0)


class ChoicesFileConfig(StrictModel):
    correct: int | None = Field(default=None, ge=0)
    incorrect: int | None = Field(default=None, ge=0)
    mmr_weight: float | None = Field(default=None, ge=0, le=1)
    random_seed: int | None = None


class LocalBuilderFileConfig(StrictModel):
    schema_version: Literal[1]
    execution: ExecutionFileConfig = Field(default_factory=ExecutionFileConfig)
    models: ModelsFileConfig = Field(default_factory=ModelsFileConfig)
    paths: PathsFileConfig = Field(default_factory=PathsFileConfig)
    benchmark: BenchmarkFileConfig = Field(default_factory=BenchmarkFileConfig)
    divergence: DivergenceFileConfig = Field(
        default_factory=DivergenceFileConfig
    )
    choices: ChoicesFileConfig = Field(default_factory=ChoicesFileConfig)


@dataclass(frozen=True)
class LocalBuilderConfig:
    """Fully resolved settings used by local stage implementations."""

    workspace: Path
    artifact_output: Path | None
    max_workers: int
    max_attempts: int
    candidate_generation_model: str
    benchmark_dataset: str = DEFAULT_BENCHMARK_DATASET
    benchmark_split: str = DEFAULT_BENCHMARK_SPLIT
    repository_remote: str = DEFAULT_REPOSITORY_REMOTE
    divergence_depth: int = DEFAULT_DIVERGENCE_DEPTH
    variable_max_depth: int = DEFAULT_VARIABLE_MAX_DEPTH
    parameter_max_depth: int = DEFAULT_PARAMETER_MAX_DEPTH
    correct_choices: int = DEFAULT_CORRECT_CHOICES
    incorrect_choices: int = DEFAULT_INCORRECT_CHOICES
    mmr_weight: float = DEFAULT_MMR_WEIGHT
    random_seed: int = DEFAULT_RANDOM_SEED
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
        benchmark_dataset = _pick(
            None,
            file_config.benchmark.dataset,
            DEFAULT_BENCHMARK_DATASET,
        )
        benchmark_split = _pick(
            None,
            file_config.benchmark.split,
            DEFAULT_BENCHMARK_SPLIT,
        )
        repository_remote = _pick(
            None,
            file_config.benchmark.repository_remote,
            DEFAULT_REPOSITORY_REMOTE,
        )
        divergence_depth = _pick(
            None,
            file_config.divergence.depth,
            DEFAULT_DIVERGENCE_DEPTH,
        )
        variable_max_depth = _pick(
            None,
            file_config.divergence.variable_max_depth,
            DEFAULT_VARIABLE_MAX_DEPTH,
        )
        parameter_max_depth = _pick(
            None,
            file_config.divergence.parameter_max_depth,
            DEFAULT_PARAMETER_MAX_DEPTH,
        )
        correct_choices = _pick(
            None,
            file_config.choices.correct,
            DEFAULT_CORRECT_CHOICES,
        )
        incorrect_choices = _pick(
            None,
            file_config.choices.incorrect,
            DEFAULT_INCORRECT_CHOICES,
        )
        mmr_weight = _pick(
            None,
            file_config.choices.mmr_weight,
            DEFAULT_MMR_WEIGHT,
        )
        random_seed = _pick(
            None,
            file_config.choices.random_seed,
            DEFAULT_RANDOM_SEED,
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

    return LocalBuilderConfig(
        workspace=workspace_path,
        artifact_output=output_path,
        max_workers=resolved_workers,
        max_attempts=resolved_attempts,
        candidate_generation_model=model,
        benchmark_dataset=benchmark_dataset,
        benchmark_split=benchmark_split,
        repository_remote=repository_remote,
        divergence_depth=divergence_depth,
        variable_max_depth=variable_max_depth,
        parameter_max_depth=parameter_max_depth,
        correct_choices=correct_choices,
        incorrect_choices=incorrect_choices,
        mmr_weight=mmr_weight,
        random_seed=random_seed,
        source=source,
    )
