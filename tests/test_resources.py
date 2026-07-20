import json
from pathlib import Path

import pytest

from explainbench.resources import load_shared_intent_artifacts
from explainbench.submission import supported_instance_ids


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("task", "stem"),
    [
        ("e2e.intent", "e2e_intent"),
        ("local.intent", "local_intent"),
    ],
)
def test_shared_intent_artifacts_match_source_dataset(task, stem):
    artifacts = load_shared_intent_artifacts(task)
    source_context = json.loads(
        (ROOT / "dataset" / "context" / f"{stem}.json").read_text(encoding="utf-8")
    )
    source_ground_truths = json.loads(
        (ROOT / "dataset" / "ground_truths" / f"{stem}.json").read_text(
            encoding="utf-8"
        )
    )

    assert artifacts.context == source_context
    assert artifacts.ground_truths == source_ground_truths
    assert artifacts.instance_ids == supported_instance_ids()
    assert len(artifacts.instance_ids) == 297


def test_shared_intent_artifact_shapes():
    instance_id = "astropy__astropy-12907"
    e2e = load_shared_intent_artifacts("e2e.intent")
    local = load_shared_intent_artifacts("local.intent")

    assert set(e2e.context[instance_id]) == {"masked_test", "choices"}
    assert isinstance(e2e.ground_truths[instance_id]["answer"], str)
    assert set(local.context[instance_id]) == {
        "function_code_before_patch",
        "function_parameters_before_patch",
        "line",
        "choices",
        "before_or_after",
    }
    assert isinstance(local.ground_truths[instance_id]["answer"], list)


def test_unknown_shared_intent_task_is_rejected():
    with pytest.raises(ValueError, match="unknown shared intent task"):
        load_shared_intent_artifacts("local.effect")
