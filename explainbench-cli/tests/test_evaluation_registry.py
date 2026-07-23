import pytest

from explainbench.evaluation.registry import (
    EvaluationMode,
    TaskName,
    resolve_task_selection,
)


def test_lite_mode_resolves_both_intent_tasks():
    selection = resolve_task_selection(mode="lite")

    assert selection.mode is EvaluationMode.LITE
    assert selection.tasks == (TaskName.E2E_INTENT, TaskName.LOCAL_INTENT)
    assert not selection.requires_effect_artifacts
    assert not selection.requires_patches


def test_full_mode_resolves_all_four_tasks():
    selection = resolve_task_selection(mode="full")

    assert selection.mode is EvaluationMode.FULL
    assert selection.tasks == (
        TaskName.E2E_INTENT,
        TaskName.E2E_EFFECT,
        TaskName.LOCAL_INTENT,
        TaskName.LOCAL_EFFECT,
    )
    assert selection.requires_effect_artifacts
    assert selection.requires_patches


def test_fine_grained_selection_preserves_order():
    selection = resolve_task_selection(
        tasks=["local.intent", "e2e.effect"],
    )

    assert selection.mode is None
    assert selection.tasks == (TaskName.LOCAL_INTENT, TaskName.E2E_EFFECT)
    assert selection.requires_effect_artifacts


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "select one --mode"),
        (
            {"mode": "lite", "tasks": ["local.intent"]},
            "mutually exclusive",
        ),
        ({"mode": "unknown"}, "unknown evaluation mode"),
        ({"tasks": ["unknown"]}, "unknown evaluation task"),
        (
            {"tasks": ["local.intent", "local.intent"]},
            "duplicate task selection",
        ),
    ],
)
def test_invalid_task_selections_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        resolve_task_selection(**kwargs)
