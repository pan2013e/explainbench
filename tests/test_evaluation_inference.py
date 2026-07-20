from types import SimpleNamespace

import pytest

from explainbench.evaluation import inference
from explainbench.evaluation.inference import Model
from explainbench.evaluation.predictions import AnswerPrediction


def test_model_requests_structured_output_and_tracks_usage(monkeypatch):
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            usage=SimpleNamespace(
                completion_tokens=2,
                prompt_tokens=10,
                total_tokens=12,
            ),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"answer": ["D"]}')
                )
            ],
        )

    monkeypatch.setattr(inference.litellm, "completion", fake_completion)
    model = Model(
        "test-model",
        n=2,
        max_retries=2,
        generation_workers=1,
    )

    predictions = model.infer("Choose an answer.", AnswerPrediction)

    assert predictions == [
        AnswerPrediction(answer=["d"]),
        AnswerPrediction(answer=["d"]),
    ]
    assert len(calls) == 2
    assert model.max_retries == 2
    assert model.generation_workers == 1
    assert all(call["response_format"] is AnswerPrediction for call in calls)
    assert all(call["messages"] == [{"role": "user", "content": "Choose an answer."}] for call in calls)
    assert all(call["n"] == 1 for call in calls)
    assert model.token_usage == {
        "completion_tokens": 4,
        "prompt_tokens": 20,
        "total_tokens": 24,
    }


def test_model_rejects_nonpositive_generation_count():
    with pytest.raises(ValueError, match="n must be at least 1"):
        Model("test-model", n=0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_retries": 0},
        {"generation_workers": 0},
    ],
)
def test_model_rejects_nonpositive_runtime_controls(kwargs):
    with pytest.raises(ValueError, match="must be at least 1"):
        Model("test-model", **kwargs)


def test_model_uses_configured_retry_count(monkeypatch):
    attempts = 0

    def flaky_completion(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary failure")
        return SimpleNamespace(
            usage=SimpleNamespace(
                completion_tokens=1,
                prompt_tokens=5,
                total_tokens=6,
            ),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"answer": ["a"]}')
                )
            ],
        )

    def zero_waits():
        yield
        while True:
            yield 0

    monkeypatch.setattr(inference.backoff, "expo", zero_waits)
    monkeypatch.setattr(inference.litellm, "completion", flaky_completion)
    model = Model("test-model", max_retries=3)

    prediction = model.infer_once("Choose an answer.", AnswerPrediction)

    assert prediction == AnswerPrediction(answer=["a"])
    assert attempts == 3
