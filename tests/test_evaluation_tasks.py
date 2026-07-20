import pytest
from pydantic import ValidationError

from explainbench.evaluation.predictions import (
    AnswerPrediction,
    E2EEffectPrediction,
)
from explainbench.evaluation.registry import TaskName
from explainbench.evaluation.schemas import (
    AnswerGroundTruth,
    E2EEffectContext,
    E2EEffectGroundTruth,
    E2EIntentContext,
    LocalEffectContext,
    LocalIntentContext,
)
from explainbench.evaluation.scoring import score_prediction
from explainbench.evaluation.tasks import build_prompt, prediction_schema


@pytest.mark.parametrize(
    ("task", "context", "expected_text"),
    [
        (
            TaskName.E2E_INTENT,
            E2EIntentContext(masked_test="assert [[MASKED 1]]", choices=["x", "y"]),
            "Masked Test:\nassert [[MASKED 1]]",
        ),
        (
            TaskName.E2E_EFFECT,
            E2EEffectContext(test_content="assert value == 2", choices=["pass", "fail"]),
            "Test Content:\nassert value == 2",
        ),
        (
            TaskName.LOCAL_INTENT,
            LocalIntentContext(
                function_code_before_patch="def example():\n    return 1",
                function_parameters_before_patch="{}",
                line="return 1",
                choices=["return 1", "return 2"],
                before_or_after="after",
            ),
            "Function Code Before Patch:\ndef example():",
        ),
        (
            TaskName.LOCAL_EFFECT,
            LocalEffectContext(
                function_code_before_patch="def example():\n    return 1",
                function_parameters_before_patch="{}",
                line="return 1",
                choices=["return value", "exception"],
                before_or_after="before",
            ),
            'Answer with JSON such as {"answer": ["a"]}',
        ),
    ],
)
def test_build_prompt_for_each_task(task, context, expected_text):
    prompt = build_prompt(task, "The return value changes.", context)

    assert "*** Explanation Start ***\nThe return value changes." in prompt
    assert expected_text in prompt
    assert "a) " in prompt
    assert "b) " in prompt


def test_e2e_effect_uses_before_and_after_prediction_schema():
    context = E2EEffectContext(test_content="assert value == 2", choices=["pass", "fail"])

    prompt = build_prompt(TaskName.E2E_EFFECT, "The behavior changes.", context)

    assert prediction_schema(TaskName.E2E_EFFECT) is E2EEffectPrediction
    assert '"before_selection"' in prompt
    assert '"after_selection"' in prompt


def test_build_prompt_rejects_context_for_different_task():
    context = E2EIntentContext(masked_test="assert [[MASKED 1]]", choices=["x", "y"])

    with pytest.raises(TypeError, match="requires E2EEffectContext"):
        build_prompt(TaskName.E2E_EFFECT, "Explanation", context)


def test_prediction_choices_are_normalized_and_duplicates_rejected():
    assert AnswerPrediction(answer=[" A ", "B"]).answer == ["a", "b"]
    assert E2EEffectPrediction(
        before_selection=" C ",
        after_selection="E",
    ).model_dump() == {"before_selection": "c", "after_selection": "e"}

    with pytest.raises(ValidationError, match="duplicate"):
        AnswerPrediction(answer=["a", "A"])


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (["a", "b"], 1.0),
        (["a"], 0.5),
        (["a", "c"], 0.0),
    ],
)
def test_answer_tasks_use_subset_credit(answer, expected):
    ground_truth = AnswerGroundTruth(answer=["a", "b"])

    assert (
        score_prediction(
            TaskName.LOCAL_EFFECT,
            AnswerPrediction(answer=answer),
            ground_truth,
        )
        == expected
    )


def test_e2e_effect_requires_both_predictions_to_match():
    ground_truth = E2EEffectGroundTruth(before_answer="c", after_answer="e")

    assert score_prediction(
        TaskName.E2E_EFFECT,
        E2EEffectPrediction(before_selection="c", after_selection="e"),
        ground_truth,
    ) == 1.0
    assert score_prediction(
        TaskName.E2E_EFFECT,
        E2EEffectPrediction(before_selection="c", after_selection="d"),
        ground_truth,
    ) == 0.0
