"""Canonical prompt builders and prediction schemas for evaluation tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping

from pydantic import BaseModel

from explainbench.evaluation.choices import format_choices
from explainbench.evaluation.predictions import (
    AnswerPrediction,
    E2EEffectPrediction,
)
from explainbench.evaluation.registry import TaskName
from explainbench.evaluation.schemas import (
    ChoicesContext,
    ContextArtifact,
    E2EEffectContext,
    E2EIntentContext,
    LocalEffectContext,
    LocalIntentContext,
)


_PROMPT_TEMPLATE = (
    "An AI agent fixed a bug in a code repository and provided an explanation for the patch. "
    "You will be given this patch explanation, and your task is to answer questions about the bug and patch described by the explanation. "
    "Your answer must be grounded only in the provided explanation; do not use outside knowledge or assumptions. "
    "You should respond in JSON format, complying with the following Pydantic schema: {schema}\n\n"
    "Patch Explanation:\n*** Explanation Start ***\n{explanation}\n*** Explanation End ***\n\n"
    "{context}"
    "Question:\n{question}\n"
)

_E2E_INTENT_QUESTION = (
    "Masked Test:\n"
    "{masked_test}\n\n"
    "Choices:\n"
    "{choices}\n\n"
    "Your task is to assess the informational content of the provided explanation. "
    "Based on the explanation and the explanation alone, what expression should go in [[MASKED 1]]? "
    "Do NOT guess based on the test content or your prior knowledge; base your answer on the explanation itself, and if the explanation lacks information, choose the \"cannot be answered\" option. "
    "After consideration, choose the correct option from the choices and answer with a single letter."
)

_E2E_EFFECT_QUESTION = (
    "Test Content:\n"
    "{test_content}\n\n"
    "Choices:\n"
    "{choices}\n\n"
    "Your task is to assess the informational content of the provided explanation from an AI agent. "
    "Based on the information in the explanation about the patch (code change) from the agent, what would happen when running the provided test both before and after applying the patch? "
    "Note that the test may behave identically before and after the patch, if the test is irrelevant or the patch is ineffective. "
    "Think carefully about both the explanation and the test itself before answering. "
    "After consideration, choose the correct option corresponding to behavior before and after the patch from the choices, answering with one letter for `before_selection` and one letter for `after_selection`. "
    "Base your answer on the explanation alone, and if the explanation lacks information, pick the \"cannot be answered\" option."
)

_LOCAL_EFFECT_QUESTION = (
    "Within the context of the provided function and inputs, immediately {before_or_after} the execution of the specified line, which of the following expressions have different values before and after the patch?\n\n"
    "Choices:\n"
    "{choices}\n\n"
    "Hints:\n"
    "1. `__return__` may be used in an expression to refer to the function's return value.\n"
    "2. `__exception__` may be used in an expression to refer to an exception caught in the function. It is a list of str with length 2. The first element is the exception type as str, and the second element is the exception message as str.\n"
    "3. The specified line may not be reached or completely executed due to an uncaught exception. For simplicity, you may treat raising such an exception as the function returning an `__exception__` object.\n"
    "4. Select one or more options. Answer with JSON such as {{\"answer\": [\"a\"]}} or {{\"answer\": [\"a\", \"b\"]}}."
)

_LOCAL_INTENT_QUESTION = (
    "Within the context of the provided function and inputs, immediately {before_or_after} the execution of the specified line, which of the following expressions best describe what the developer-intended change is?\n\n"
    "Choices:\n"
    "{choices}\n\n"
    "Hints:\n"
    "1. `__return__` may be used in an expression to refer to the function's return value.\n"
    "2. `__exception__` may be used in an expression to refer to an exception caught in the function. It is a list of str with length 2. The first element is the exception type as str, and the second element is the exception message as str.\n"
    "3. The specified line may not be reached or completely executed due to an uncaught exception. For simplicity, you may treat raising such an exception as the function returning an `__exception__` object.\n"
    "4. Select one or more options. Answer with JSON such as {{\"answer\": [\"a\"]}} or {{\"answer\": [\"a\", \"b\"]}}."
)


@dataclass(frozen=True)
class TaskDefinition:
    name: TaskName
    context_schema: type[ChoicesContext]
    prediction_schema: type[BaseModel]
    question_template: str


TASK_DEFINITIONS: Mapping[TaskName, TaskDefinition] = {
    TaskName.E2E_INTENT: TaskDefinition(
        name=TaskName.E2E_INTENT,
        context_schema=E2EIntentContext,
        prediction_schema=AnswerPrediction,
        question_template=_E2E_INTENT_QUESTION,
    ),
    TaskName.E2E_EFFECT: TaskDefinition(
        name=TaskName.E2E_EFFECT,
        context_schema=E2EEffectContext,
        prediction_schema=E2EEffectPrediction,
        question_template=_E2E_EFFECT_QUESTION,
    ),
    TaskName.LOCAL_INTENT: TaskDefinition(
        name=TaskName.LOCAL_INTENT,
        context_schema=LocalIntentContext,
        prediction_schema=AnswerPrediction,
        question_template=_LOCAL_INTENT_QUESTION,
    ),
    TaskName.LOCAL_EFFECT: TaskDefinition(
        name=TaskName.LOCAL_EFFECT,
        context_schema=LocalEffectContext,
        prediction_schema=AnswerPrediction,
        question_template=_LOCAL_EFFECT_QUESTION,
    ),
}


@lru_cache(maxsize=None)
def _schema_string(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(mode="serialization"))


def _format_context(values: Mapping[str, str]) -> str:
    def label(key: str) -> str:
        return " ".join(word.capitalize() for word in key.split("_"))

    return "\n\n".join(f"{label(key)}:\n{value}" for key, value in values.items()) + "\n\n"


def _question_and_context(
    task: TaskName,
    context: ContextArtifact,
) -> tuple[str, str]:
    choices = format_choices(context.choices)
    if task is TaskName.E2E_INTENT and isinstance(context, E2EIntentContext):
        return (
            _E2E_INTENT_QUESTION.format(
                masked_test=context.masked_test,
                choices=choices,
            ),
            "",
        )
    if task is TaskName.E2E_EFFECT and isinstance(context, E2EEffectContext):
        return (
            _E2E_EFFECT_QUESTION.format(
                test_content=context.test_content,
                choices=choices,
            ),
            "",
        )
    if isinstance(context, (LocalIntentContext, LocalEffectContext)):
        template = (
            _LOCAL_INTENT_QUESTION
            if task is TaskName.LOCAL_INTENT
            else _LOCAL_EFFECT_QUESTION
        )
        question = template.format(
            before_or_after=context.before_or_after,
            choices=choices,
        )
        rendered_context = _format_context(
            {
                "function_code_before_patch": context.function_code_before_patch,
                "function_parameters_before_patch": context.function_parameters_before_patch,
                "line": context.line,
            }
        )
        return question, rendered_context
    raise TypeError(f"context {type(context).__name__} is incompatible with {task.value}")


def build_prompt(
    task: str | TaskName,
    explanation: str,
    context: ContextArtifact,
) -> str:
    """Build the canonical evaluator prompt for one task instance."""

    parsed_task = TaskName(task)
    definition = TASK_DEFINITIONS[parsed_task]
    if not isinstance(context, definition.context_schema):
        raise TypeError(
            f"{parsed_task.value} requires {definition.context_schema.__name__}, "
            f"got {type(context).__name__}"
        )
    question, rendered_context = _question_and_context(parsed_task, context)
    return _PROMPT_TEMPLATE.format(
        schema=_schema_string(definition.prediction_schema),
        explanation=explanation,
        context=rendered_context,
        question=question,
    )


def prediction_schema(task: str | TaskName) -> type[BaseModel]:
    """Return the structured response schema for a task."""

    return TASK_DEFINITIONS[TaskName(task)].prediction_schema
