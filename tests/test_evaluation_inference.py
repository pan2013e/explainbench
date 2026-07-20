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
    model = Model("test-model", n=2)

    predictions = model.infer("Choose an answer.", AnswerPrediction)

    assert predictions == [
        AnswerPrediction(answer=["d"]),
        AnswerPrediction(answer=["d"]),
    ]
    assert len(calls) == 2
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
