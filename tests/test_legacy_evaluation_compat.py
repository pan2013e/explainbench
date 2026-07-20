from evaluation.inference import Model as LegacyModel
from evaluation.schema import MCQ
from evaluation.task import E2E, Local, Task

from explainbench.evaluation.inference import Model
from explainbench.evaluation.predictions import (
    AnswerPrediction,
    E2EEffectPrediction,
)


class FakeModel:
    def __init__(self):
        self.prompt = None
        self.schema = None

    def infer(self, prompt, schema):
        self.prompt = prompt
        self.schema = schema
        return [schema.model_validate({"answer": ["a"]})]


def test_legacy_imports_point_to_canonical_package_objects():
    assert LegacyModel is Model
    assert MCQ is AnswerPrediction


def test_legacy_task_registry_contains_all_canonical_tasks():
    assert set(Task._registry) == {
        "e2e.intent",
        "e2e.effect",
        "local.intent",
        "local.effect",
    }
    assert Task.get_task("e2e.effect") is E2E.Effect
    assert Task.get_task("LOCAL.INTENT") is Local.Intent
    assert E2E.Effect.SCHEMA is E2EEffectPrediction


def test_legacy_predict_and_eval_delegate_to_canonical_implementation():
    model = FakeModel()
    predictions = E2E.Intent.predict(
        model,
        "Option a is correct.",
        masked_test="assert [[MASKED 1]]",
        choices=["first", "second"],
    )

    assert model.schema is AnswerPrediction
    assert "Masked Test:" in model.prompt
    assert E2E.Intent.eval(predictions, {"answer": "A"}) == [1.0]
