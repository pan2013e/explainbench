import random

from explainbench.question_builders.local.stages.build_answer_choices import (
    NO_EFFECT_CHOICE,
    build_choices,
)


def test_build_choices_selects_one_correct_and_three_distractors():
    correct = ["result.value"]
    incorrect = ["result", "value", "other", "unrelated"]

    choices, answer = build_choices(
        correct_pool=correct,
        incorrect_pool=incorrect,
        correct_count=1,
        incorrect_count=3,
        mmr_weight=0.7,
        randomizer=random.Random(42),
        fallback_to_gold=False,
    )

    assert len(choices) == 6
    assert choices[-2] == NO_EFFECT_CHOICE
    assert choices[-1] == "Cannot be answered by the explanation alone"
    assert len(answer) == 1
    assert choices[ord(answer[0]) - ord("a")] == "result.value"
    assert correct == ["result.value"]
    assert incorrect == ["result", "value", "other", "unrelated"]


def test_gold_fallback_makes_no_effect_the_only_answer():
    choices, answer = build_choices(
        correct_pool=["would.change"],
        incorrect_pool=["first", "second", "third"],
        correct_count=1,
        incorrect_count=3,
        mmr_weight=0.7,
        randomizer=random.Random(42),
        fallback_to_gold=True,
    )

    assert choices[-2] == NO_EFFECT_CHOICE
    assert answer == ["e"]

