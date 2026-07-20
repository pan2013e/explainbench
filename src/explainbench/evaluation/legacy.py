"""Compatibility classes for the repository's original evaluation entry point."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from explainbench.evaluation.registry import TASK_SPECS, TaskName
from explainbench.evaluation.scoring import score_prediction, validate_ground_truth
from explainbench.evaluation.tasks import TASK_DEFINITIONS, build_prompt


class Task:
    """Legacy class-based facade backed by canonical package task definitions."""

    TASK_NAME: ClassVar[TaskName | None] = None
    SCHEMA: ClassVar[type[BaseModel]]
    CTX_AGENT_SPECIFIC: ClassVar[bool]
    QUESTION: ClassVar[str]
    _registry: ClassVar[dict[str, type["Task"]]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.TASK_NAME is None:
            return
        definition = TASK_DEFINITIONS[cls.TASK_NAME]
        cls.SCHEMA = definition.prediction_schema
        cls.QUESTION = definition.question_template
        cls.CTX_AGENT_SPECIFIC = not TASK_SPECS[cls.TASK_NAME].uses_shared_artifacts
        cls._registry[cls.TASK_NAME.value] = cls

    @classmethod
    def repr(cls) -> str:
        if cls.TASK_NAME is None:
            raise ValueError("base Task does not identify an evaluation task")
        return cls.TASK_NAME.value.replace(".", "_")

    @classmethod
    def get_task(cls, name: str) -> type["Task"]:
        normalized = name.lower()
        if normalized not in cls._registry:
            raise ValueError(
                f"Unknown task name: {name}, available tasks: {list(cls._registry)}"
            )
        return cls._registry[normalized]

    @classmethod
    def _build_prompt(cls, explanation: str, **context) -> str:
        if cls.TASK_NAME is None:
            raise ValueError("base Task cannot build a prompt")
        context_model = TASK_DEFINITIONS[cls.TASK_NAME].context_schema.model_validate(
            context
        )
        return build_prompt(cls.TASK_NAME, explanation, context_model)

    @classmethod
    def predict(cls, model, explanation: str, **context) -> list[BaseModel]:
        prompt = cls._build_prompt(explanation, **context)
        return model.infer(prompt, cls.SCHEMA)

    @classmethod
    def eval(cls, pred: list[BaseModel], gt: dict) -> list[float]:
        if cls.TASK_NAME is None:
            raise ValueError("base Task cannot score predictions")
        ground_truth = validate_ground_truth(cls.TASK_NAME, gt)
        return [
            score_prediction(cls.TASK_NAME, prediction, ground_truth)
            for prediction in pred
        ]


class E2E:
    class Effect(Task):
        TASK_NAME = TaskName.E2E_EFFECT

    class Intent(Task):
        TASK_NAME = TaskName.E2E_INTENT


class Local:
    class Effect(Task):
        TASK_NAME = TaskName.LOCAL_EFFECT

    class Intent(Task):
        TASK_NAME = TaskName.LOCAL_INTENT
