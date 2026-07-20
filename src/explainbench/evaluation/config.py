"""Versioned TOML configuration for ExplainBench evaluation."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from pydantic import Field, ValidationError, field_validator, model_validator

from explainbench.evaluation.registry import (
    EvaluationMode,
    TaskName,
    TaskSelection,
    resolve_task_selection,
)
from explainbench.schemas import StrictModel


DEFAULT_EVALUATOR_MODEL = "gpt-5-mini-2025-08-07"
DEFAULT_NUM_GENERATIONS = 5
DEFAULT_INSTANCE_WORKERS = 10
DEFAULT_GENERATION_WORKERS = 10
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 1.0
DEFAULT_MAX_TOKENS = 8192
DEFAULT_MAX_RETRIES = 5


class EvaluationConfigError(ValueError):
    """Raised when an evaluation config cannot be loaded or resolved."""


class SelectionFileConfig(StrictModel):
    mode: str | None = None
    tasks: list[str] | None = None

    @model_validator(mode="after")
    def reject_mode_with_tasks(self):
        if self.mode is not None and self.tasks:
            raise ValueError(
                "selection.mode and selection.tasks are mutually exclusive"
            )
        return self


class EvaluatorFileConfig(StrictModel):
    model: str | None = None
    num_generations: int | None = Field(default=None, ge=1)
    instance_workers: int | None = Field(default=None, ge=1)
    generation_workers: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_retries: int | None = Field(default=None, ge=1)

    @field_validator("model")
    @classmethod
    def reject_blank_model(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must be a nonempty string")
        return value


class PathsFileConfig(StrictModel):
    output: str | None = None
    artifacts_dir: str | None = None

    @field_validator("output", "artifacts_dir")
    @classmethod
    def reject_blank_paths(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must be a nonempty path")
        return value


class EnvironmentFileConfig(StrictModel):
    env_file: str | None = None

    @field_validator("env_file")
    @classmethod
    def reject_blank_path(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must be a nonempty path")
        return value


class EvaluationFileConfig(StrictModel):
    schema_version: Literal[1]
    selection: SelectionFileConfig = Field(default_factory=SelectionFileConfig)
    evaluator: EvaluatorFileConfig = Field(default_factory=EvaluatorFileConfig)
    paths: PathsFileConfig = Field(default_factory=PathsFileConfig)
    environment: EnvironmentFileConfig = Field(
        default_factory=EnvironmentFileConfig
    )


class EvaluatorSettings(StrictModel):
    model: str
    num_generations: int = Field(ge=1)
    instance_workers: int = Field(ge=1)
    generation_workers: int = Field(ge=1)
    temperature: float = Field(ge=0)
    top_p: float = Field(gt=0, le=1)
    max_tokens: int = Field(ge=1)
    max_retries: int = Field(ge=1)

    @field_validator("model")
    @classmethod
    def reject_blank_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a nonempty string")
        return value


@dataclass(frozen=True)
class ResolvedEvaluationConfig:
    selection: TaskSelection
    evaluator: EvaluatorSettings
    output: Path
    artifacts_dir: Path | None
    env_file: Path | None
    source: Path | None


def _validation_message(error: ValidationError) -> str:
    detail = error.errors(include_url=False, include_context=False)[0]
    location = ".".join(str(part) for part in detail["loc"])
    message = detail["msg"]
    if message.startswith("Value error, "):
        message = message.removeprefix("Value error, ")
    return f"{location}: {message}" if location else message


def load_evaluation_config(path: str | Path) -> tuple[EvaluationFileConfig, Path]:
    """Load and validate one versioned TOML configuration file."""

    source = Path(path).expanduser().resolve()
    try:
        with source.open("rb") as config_file:
            payload = tomllib.load(config_file)
    except OSError as error:
        raise EvaluationConfigError(
            f"cannot read evaluation config {source}: {error.strerror or error}"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise EvaluationConfigError(
            f"evaluation config {source} is not valid TOML: {error}"
        ) from error
    try:
        return EvaluationFileConfig.model_validate(payload), source
    except ValidationError as error:
        raise EvaluationConfigError(
            f"invalid evaluation config {source}: {_validation_message(error)}"
        ) from error


def _config_path(value: str | None, source: Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and source is not None:
        path = source.parent / path
    return path.resolve()


def _pick(cli_value, config_value, default=None):
    if cli_value is not None:
        return cli_value
    if config_value is not None:
        return config_value
    return default


def resolve_evaluation_config(
    config: EvaluationFileConfig | None = None,
    *,
    source: Path | None = None,
    mode: str | EvaluationMode | None = None,
    tasks: Sequence[str | TaskName] | None = None,
    model: str | None = None,
    num_generations: int | None = None,
    instance_workers: int | None = None,
    generation_workers: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    max_retries: int | None = None,
    output: str | Path | None = None,
    artifacts_dir: str | Path | None = None,
    env_file: str | Path | None = None,
) -> ResolvedEvaluationConfig:
    """Merge CLI values over a config file and package defaults."""

    file_config = config or EvaluationFileConfig(schema_version=1)
    if mode is not None:
        selected_mode = mode
        selected_tasks = None
    elif tasks:
        selected_mode = None
        selected_tasks = tasks
    else:
        selected_mode = file_config.selection.mode
        selected_tasks = file_config.selection.tasks
    try:
        selection = resolve_task_selection(
            mode=selected_mode,
            tasks=selected_tasks,
        )
        evaluator = EvaluatorSettings(
            model=_pick(model, file_config.evaluator.model, DEFAULT_EVALUATOR_MODEL),
            num_generations=_pick(
                num_generations,
                file_config.evaluator.num_generations,
                DEFAULT_NUM_GENERATIONS,
            ),
            instance_workers=_pick(
                instance_workers,
                file_config.evaluator.instance_workers,
                DEFAULT_INSTANCE_WORKERS,
            ),
            generation_workers=_pick(
                generation_workers,
                file_config.evaluator.generation_workers,
                DEFAULT_GENERATION_WORKERS,
            ),
            temperature=_pick(
                temperature,
                file_config.evaluator.temperature,
                DEFAULT_TEMPERATURE,
            ),
            top_p=_pick(top_p, file_config.evaluator.top_p, DEFAULT_TOP_P),
            max_tokens=_pick(
                max_tokens,
                file_config.evaluator.max_tokens,
                DEFAULT_MAX_TOKENS,
            ),
            max_retries=_pick(
                max_retries,
                file_config.evaluator.max_retries,
                DEFAULT_MAX_RETRIES,
            ),
        )
    except (ValueError, ValidationError) as error:
        if isinstance(error, ValidationError):
            message = _validation_message(error)
        else:
            message = str(error)
        raise EvaluationConfigError(message) from error

    if output is not None:
        output_path = Path(output).expanduser()
    else:
        output_path = _config_path(file_config.paths.output, source)
    if output_path is None:
        raise EvaluationConfigError(
            "an output path is required via --output or paths.output"
        )

    if artifacts_dir is not None:
        artifact_path = Path(artifacts_dir).expanduser()
    else:
        artifact_path = _config_path(file_config.paths.artifacts_dir, source)
    if env_file is not None:
        environment_path = Path(env_file).expanduser()
    else:
        environment_path = _config_path(file_config.environment.env_file, source)
    if environment_path is not None and not environment_path.is_file():
        raise EvaluationConfigError(
            f"environment file does not exist: {environment_path}"
        )

    return ResolvedEvaluationConfig(
        selection=selection,
        evaluator=evaluator,
        output=output_path,
        artifacts_dir=artifact_path,
        env_file=environment_path,
        source=source,
    )
