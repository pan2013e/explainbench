import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dataset.extract_ground_truths.effect import build_step2
from dataset.extract_ground_truths.effect.paid_inference import (
    PaidInferenceJournal,
)
from explainbench.evaluation import inference
from explainbench.evaluation.inference import (
    InferencePersistenceError,
    Model,
)
from explainbench.evaluation.predictions import AnswerPrediction


AGENT = "test-agent"
INSTANCE_ID = "repo__project-1"
RAW_EXPRESSION_RESPONSE = (
    '{"expressions":[{"expr":"value"},{"expr":"other"}]}'
)


def _divergence() -> dict[str, object]:
    return {
        "file_path": "example.py",
        "function_name": "example:changed",
        "buggy_event_type": "Line",
        "patched_event_type": "Line",
        "buggy_statement": "return old",
        "patched_statement": "return new",
        "before_or_after": "before",
        "buggy_lineno": 10,
        "patched_lineno": 11,
        "buggy_line_count": 1,
        "patched_line_count": 1,
        "test_id": 0,
        "diff": {"values_changed": {}},
        "buggy_variables": {"value": 1},
        "patched_variables": {"value": 2},
        "agent": AGENT,
        "instance_id": INSTANCE_ID,
    }


def _agent_data() -> dict[str, dict[str, dict[str, object]]]:
    return {AGENT: {INSTANCE_ID: _divergence()}}


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_journal_records_exact_prompt_and_responses_with_checksums(tmp_path):
    journal = PaidInferenceJournal(
        tmp_path / "model-audit",
        prompt="exact prompt",
        model_id="test-model",
        reasoning_effort="medium",
        response_schema="test.Schema",
    )

    invalid = journal.record_response("not valid JSON")
    valid = journal.record_response(RAW_EXPRESSION_RESPONSE)
    journal.select_response(valid)

    manifest = json.loads(journal.manifest_path.read_text(encoding="utf-8"))
    assert journal.prompt_path.read_text(encoding="utf-8") == "exact prompt"
    assert manifest["request"]["prompt"]["sha256"] == _sha256("exact prompt")
    assert [item["sha256"] for item in manifest["responses"]] == [
        _sha256("not valid JSON"),
        _sha256(RAW_EXPRESSION_RESPONSE),
    ]
    assert manifest["selected_response"]["sha256"] == valid["sha256"]
    assert invalid["path"] == "responses/response-0001.txt"
    assert valid["path"] == "responses/response-0002.txt"

    with pytest.raises(ValueError, match="different request"):
        PaidInferenceJournal(
            journal.directory,
            prompt="different prompt",
            model_id="test-model",
            reasoning_effort="medium",
            response_schema="test.Schema",
        )
    assert journal.prompt_path.read_text(encoding="utf-8") == "exact prompt"


def test_candidate_generation_reuses_paid_response_after_interruption(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        build_step2,
        "get_function_code",
        lambda *args, **kwargs: (
            "def changed(value):\n    return value",
            "def changed(value):\n    return value + 1",
        ),
    )
    monkeypatch.setattr(
        build_step2,
        "get_agent_patch",
        lambda *args, **kwargs: "patch",
    )
    inference_calls = 0

    def interrupted_inference(
        prompt,
        model_id,
        reasoning_effort,
        env_file,
        max_retries,
        raw_response_callback,
    ):
        nonlocal inference_calls
        inference_calls += 1
        raw_response_callback(RAW_EXPRESSION_RESPONSE)
        raise KeyboardInterrupt("simulated process interruption")

    monkeypatch.setattr(
        build_step2,
        "infer_expressions",
        interrupted_inference,
    )
    first_audit = tmp_path / "attempt-1" / "model-audit"

    with pytest.raises(KeyboardInterrupt, match="simulated"):
        build_step2.process_agent(
            _agent_data(),
            AGENT,
            [INSTANCE_ID],
            1,
            1,
            True,
            predictions_path="predictions.json",
            max_workers=1,
            model_id="test-model",
            reasoning_effort="medium",
            max_retries=1,
            audit_dir=first_audit,
        )

    first_manifest = json.loads(
        (first_audit / "manifest.json").read_text(encoding="utf-8")
    )
    assert first_manifest["responses"][0]["sha256"] == _sha256(
        RAW_EXPRESSION_RESPONSE
    )
    assert first_manifest["selected_response"] is None

    def unexpected_inference(*args, **kwargs):
        raise AssertionError("a completed paid response was requested again")

    monkeypatch.setattr(
        build_step2,
        "infer_expressions",
        unexpected_inference,
    )
    second_audit = tmp_path / "attempt-2" / "model-audit"
    result = build_step2.process_agent(
        _agent_data(),
        AGENT,
        [INSTANCE_ID],
        1,
        1,
        True,
        predictions_path="predictions.json",
        max_workers=1,
        model_id="test-model",
        reasoning_effort="medium",
        max_retries=1,
        audit_dir=second_audit,
        resume_audit_dirs=(first_audit,),
    )

    candidates = result[INSTANCE_ID]
    assert inference_calls == 1
    assert candidates["changed_candidates"] == ["value"]
    assert candidates["unchanged_candidates"] == ["other"]
    assert candidates["_source_response"]["sha256"] == _sha256(
        RAW_EXPRESSION_RESPONSE
    )
    second_manifest = json.loads(
        (second_audit / "manifest.json").read_text(encoding="utf-8")
    )
    assert second_manifest["selected_response"] == (
        candidates["_source_response"]
    )
    assert second_manifest["responses"][0]["reused_from"]["sha256"] == (
        candidates["_source_response"]["sha256"]
    )


def test_response_storage_failure_does_not_repeat_model_request(
    monkeypatch,
):
    calls = 0

    def fake_completion(**kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            usage=SimpleNamespace(
                completion_tokens=2,
                prompt_tokens=3,
                total_tokens=5,
            ),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"answer":["a"]}')
                )
            ],
        )

    monkeypatch.setattr(inference.litellm, "completion", fake_completion)
    model = Model("test-model", max_retries=3)

    def fail_storage(content):
        raise OSError("disk unavailable")

    with pytest.raises(InferencePersistenceError):
        model.infer_once(
            "prompt",
            AnswerPrediction,
            raw_response_callback=fail_storage,
        )

    assert calls == 1


def test_model_records_raw_response_before_schema_parsing(
    tmp_path,
    monkeypatch,
):
    raw_response = '{"unexpected":"field"}'

    def fake_completion(**kwargs):
        return SimpleNamespace(
            usage=SimpleNamespace(
                completion_tokens=2,
                prompt_tokens=3,
                total_tokens=5,
            ),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=raw_response)
                )
            ],
        )

    monkeypatch.setattr(inference.litellm, "completion", fake_completion)
    journal = PaidInferenceJournal(
        tmp_path / "model-audit",
        prompt="prompt",
        model_id="test-model",
        reasoning_effort="medium",
        response_schema=(
            "explainbench.evaluation.predictions.AnswerPrediction"
        ),
    )
    model = Model("test-model", max_retries=1)

    with pytest.raises(ValidationError):
        model.infer_once(
            "prompt",
            AnswerPrediction,
            raw_response_callback=journal.record_response,
        )

    response_path = journal.directory / "responses" / "response-0001.txt"
    assert response_path.read_text(encoding="utf-8") == raw_response
    manifest = json.loads(journal.manifest_path.read_text(encoding="utf-8"))
    assert manifest["responses"][0]["sha256"] == _sha256(raw_response)
