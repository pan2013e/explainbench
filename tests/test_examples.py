from pathlib import Path

from pydantic import BaseModel

from explainbench.evaluation.config import (
    load_evaluation_config,
    resolve_evaluation_config,
)
from explainbench.evaluation.service import evaluate_submission
from explainbench.submission import ValidationProfile, load_submission


ROOT = Path(__file__).resolve().parents[1]
INTENT_SUBMISSION_PATH = ROOT / "examples/submission-intent.json"
INTENT_CONFIG_PATH = ROOT / "examples/evaluation-intent.toml"
EFFECT_SUBMISSION_PATH = ROOT / "examples/submission-effect.json"
EFFECT_CONFIG_PATH = ROOT / "examples/evaluation-effect.toml"


class FakeEvaluator:
    token_usage = {
        "completion_tokens": 3,
        "prompt_tokens": 30,
        "total_tokens": 33,
    }

    def __init__(self, num_generations):
        self.num_generations = num_generations

    def infer(
        self,
        messages: str | list[dict[str, str]],
        schema: type[BaseModel],
    ) -> list[BaseModel]:
        if "before_selection" in schema.model_fields:
            payload = {
                "before_selection": "a",
                "after_selection": "a",
            }
        else:
            payload = {"answer": ["a"]}
        return [
            schema.model_validate(payload)
            for _ in range(self.num_generations)
        ]


def test_intent_examples_validate_and_run_lite_mode_with_mocked_inference():
    submission = load_submission(INTENT_SUBMISSION_PATH)
    file_config, source = load_evaluation_config(INTENT_CONFIG_PATH)
    config = resolve_evaluation_config(file_config, source=source)

    result = evaluate_submission(
        submission,
        mode=config.selection.mode,
        model_id=config.evaluator.model,
        num_generations=config.evaluator.num_generations,
        workers=config.evaluator.instance_workers,
        generation_workers=config.evaluator.generation_workers,
        temperature=config.evaluator.temperature,
        top_p=config.evaluator.top_p,
        max_tokens=config.evaluator.max_tokens,
        max_retries=config.evaluator.max_retries,
        inference_model=FakeEvaluator(config.evaluator.num_generations),
    )

    assert len(submission.instances) == 3
    assert config.evaluator.num_generations == 1
    assert config.output == ROOT / "results/lite-example.json"
    assert [task.value for task in result.selection.tasks] == [
        "e2e.intent",
        "local.intent",
    ]
    assert all(task.counts.evaluated == 3 for task in result.tasks.values())
    assert all(not task.failures for task in result.tasks.values())


def test_effect_examples_validate_and_run_full_mode_with_mocked_inference():
    submission = load_submission(
        EFFECT_SUBMISSION_PATH,
        profile=ValidationProfile.FULL,
    )
    file_config, source = load_evaluation_config(EFFECT_CONFIG_PATH)
    config = resolve_evaluation_config(file_config, source=source)

    result = evaluate_submission(
        submission,
        mode=config.selection.mode,
        model_id=config.evaluator.model,
        num_generations=config.evaluator.num_generations,
        workers=config.evaluator.instance_workers,
        generation_workers=config.evaluator.generation_workers,
        temperature=config.evaluator.temperature,
        top_p=config.evaluator.top_p,
        max_tokens=config.evaluator.max_tokens,
        max_retries=config.evaluator.max_retries,
        artifacts_dir=config.artifacts_dir,
        inference_model=FakeEvaluator(config.evaluator.num_generations),
    )

    assert config.artifacts_dir == ROOT / "examples/question-artifacts"
    assert config.output == ROOT / "results/effect-example.json"
    assert [task.value for task in result.selection.tasks] == [
        "e2e.intent",
        "e2e.effect",
        "local.intent",
        "local.effect",
    ]
    assert all(task.counts.evaluated == 1 for task in result.tasks.values())
    assert all(not task.failures for task in result.tasks.values())
