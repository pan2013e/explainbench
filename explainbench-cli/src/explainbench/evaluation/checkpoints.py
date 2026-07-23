"""Incremental, versioned checkpoints for resumable evaluation runs."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from explainbench.evaluation.config import EvaluatorSettings
from explainbench.evaluation.preparation import PreparedEvaluation
from explainbench.evaluation.registry import TaskName
from explainbench.evaluation.runner import InstanceRunResult
from explainbench.evaluation.tasks import prediction_schema


CHECKPOINT_SCHEMA_VERSION = 1


class EvaluationCheckpointError(ValueError):
    """Raised when an evaluation checkpoint cannot be safely reused."""


def checkpoint_path_for_output(output: str | Path) -> Path:
    """Return the deterministic sidecar checkpoint path for a result file."""

    output_path = Path(output)
    return output_path.with_name(f"{output_path.name}.checkpoint.jsonl")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def evaluation_fingerprint(
    prepared: PreparedEvaluation,
    settings: EvaluatorSettings,
) -> str:
    """Fingerprint every input that can change generated predictions or scores."""

    tasks: dict[str, Any] = {}
    for task, prepared_task in prepared.tasks.items():
        instance_ids = prepared_task.evaluable_instance_ids
        tasks[task.value] = {
            "context": {
                instance_id: prepared_task.artifacts.context[
                    instance_id
                ].model_dump(mode="json")
                for instance_id in instance_ids
            },
            "ground_truths": {
                instance_id: prepared_task.artifacts.ground_truths[
                    instance_id
                ].model_dump(mode="json")
                for instance_id in instance_ids
            },
        }

    payload = {
        "submission": prepared.submission.model_dump(mode="json"),
        "selection": {
            "mode": (
                prepared.selection.mode.value
                if prepared.selection.mode is not None
                else None
            ),
            "tasks": [task.value for task in prepared.selection.tasks],
        },
        "evaluator": {
            "model": settings.model,
            "num_generations": settings.num_generations,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "max_tokens": settings.max_tokens,
        },
        "tasks": tasks,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_token_usage(value: Any, *, line_number: int) -> dict[str, int]:
    if not isinstance(value, dict):
        raise EvaluationCheckpointError(
            f"checkpoint line {line_number} has invalid token_usage"
        )
    token_usage: dict[str, int] = {}
    for key, count in value.items():
        if (
            not isinstance(key, str)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
        ):
            raise EvaluationCheckpointError(
                f"checkpoint line {line_number} has invalid token_usage"
            )
        token_usage[key] = count
    return token_usage


@dataclass
class EvaluationCheckpoint:
    """Append completed task instances and reload them after interruption."""

    path: Path
    fingerprint: str
    prepared: PreparedEvaluation
    num_generations: int
    completed: dict[TaskName, dict[str, InstanceRunResult]] = field(
        default_factory=dict
    )
    token_usage: dict[str, int] = field(default_factory=dict)

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        prepared: PreparedEvaluation,
        settings: EvaluatorSettings,
        resume: bool,
    ) -> "EvaluationCheckpoint":
        checkpoint = cls(
            path=Path(path),
            fingerprint=evaluation_fingerprint(prepared, settings),
            prepared=prepared,
            num_generations=settings.num_generations,
            completed={task: {} for task in prepared.selection.tasks},
        )
        if resume and checkpoint.path.is_file():
            checkpoint._load()
        else:
            checkpoint._initialize()
        return checkpoint

    @property
    def completed_count(self) -> int:
        return sum(len(instances) for instances in self.completed.values())

    def _metadata(self) -> dict[str, Any]:
        return {
            "record_type": "metadata",
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "fingerprint": self.fingerprint,
            "submission_id": self.prepared.submission.submission_id,
            "tasks": [task.value for task in self.prepared.selection.tasks],
        }

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        try:
            temporary.write_text(
                f"{_canonical_json(self._metadata())}\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise EvaluationCheckpointError(
                f"cannot read checkpoint {self.path}: {error}"
            ) from error
        lines = raw.splitlines()
        if not lines:
            raise EvaluationCheckpointError(f"checkpoint {self.path} is empty")

        records: list[dict[str, Any]] = []
        for index, line in enumerate(lines, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                is_incomplete_final_line = index == len(lines) and not raw.endswith("\n")
                if is_incomplete_final_line:
                    break
                raise EvaluationCheckpointError(
                    f"checkpoint {self.path} has invalid JSON on line {index}: "
                    f"{error.msg}"
                ) from error
            if not isinstance(record, dict):
                raise EvaluationCheckpointError(
                    f"checkpoint {self.path} line {index} must be a JSON object"
                )
            records.append(record)

        if not records:
            raise EvaluationCheckpointError(
                f"checkpoint {self.path} has no complete metadata record"
            )
        metadata = records[0]
        if (
            metadata.get("record_type") != "metadata"
            or metadata.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        ):
            raise EvaluationCheckpointError(
                f"checkpoint {self.path} has unsupported metadata"
            )
        if metadata.get("fingerprint") != self.fingerprint:
            raise EvaluationCheckpointError(
                "checkpoint does not match the current submission, selected tasks, "
                "artifacts, or evaluator settings; rerun without --resume to start over"
            )

        valid_instances = {
            task: set(prepared_task.evaluable_instance_ids)
            for task, prepared_task in self.prepared.tasks.items()
        }
        for line_number, record in enumerate(records[1:], start=2):
            record_type = record.get("record_type")
            if record_type == "usage":
                self.token_usage = _validate_token_usage(
                    record.get("token_usage"),
                    line_number=line_number,
                )
                continue
            if record_type != "instance":
                raise EvaluationCheckpointError(
                    f"checkpoint line {line_number} has unknown record_type"
                )
            try:
                task = TaskName(record["task"])
                instance_id = record["instance_id"]
                raw_predictions = record["predictions"]
                raw_scores = record["scores"]
            except (KeyError, ValueError, TypeError) as error:
                raise EvaluationCheckpointError(
                    f"checkpoint line {line_number} has invalid instance metadata"
                ) from error
            if (
                task not in valid_instances
                or not isinstance(instance_id, str)
                or instance_id not in valid_instances[task]
                or not isinstance(raw_predictions, list)
                or not isinstance(raw_scores, list)
                or len(raw_predictions) != len(raw_scores)
                or len(raw_predictions) != self.num_generations
            ):
                raise EvaluationCheckpointError(
                    f"checkpoint line {line_number} has invalid instance result"
                )
            schema = prediction_schema(task)
            try:
                predictions = tuple(
                    schema.model_validate(prediction)
                    for prediction in raw_predictions
                )
                scores = tuple(float(score) for score in raw_scores)
            except (ValueError, TypeError) as error:
                raise EvaluationCheckpointError(
                    f"checkpoint line {line_number} has invalid predictions or scores"
                ) from error
            if not all(math.isfinite(score) for score in scores):
                raise EvaluationCheckpointError(
                    f"checkpoint line {line_number} has non-finite scores"
                )
            self.completed[task][instance_id] = InstanceRunResult(
                predictions=predictions,
                scores=scores,
            )
            self.token_usage = _validate_token_usage(
                record.get("token_usage", {}),
                line_number=line_number,
            )

    def _append(self, record: Mapping[str, Any]) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as checkpoint_file:
                checkpoint_file.write(f"{_canonical_json(record)}\n")
                checkpoint_file.flush()
                os.fsync(checkpoint_file.fileno())
        except (OSError, TypeError, ValueError) as error:
            raise EvaluationCheckpointError(
                f"cannot write checkpoint {self.path}: {error}"
            ) from error

    def record_instance(
        self,
        task: TaskName,
        instance_id: str,
        result: InstanceRunResult,
        token_usage: Mapping[str, int],
    ) -> None:
        usage = dict(token_usage)
        self._append(
            {
                "record_type": "instance",
                "task": task.value,
                "instance_id": instance_id,
                "predictions": [
                    prediction.model_dump(mode="json")
                    for prediction in result.predictions
                ],
                "scores": list(result.scores),
                "token_usage": usage,
            }
        )
        self.completed[task][instance_id] = result
        self.token_usage = usage

    def record_usage(self, token_usage: Mapping[str, int]) -> None:
        usage = dict(token_usage)
        self._append({"record_type": "usage", "token_usage": usage})
        self.token_usage = usage

    def remove(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as error:
            raise EvaluationCheckpointError(
                f"cannot remove completed checkpoint {self.path}: {error}"
            ) from error
