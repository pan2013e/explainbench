import json
from pathlib import Path

import pytest

from explainbench.evaluation.artifacts import (
    ArtifactResolutionError,
    ArtifactValidationError,
    load_task_artifacts,
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


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_ARTIFACT_ROOT = ROOT.parent / "dataset"
AGENT = "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct"
INSTANCE_ID = "astropy__astropy-12907"
SECOND_INSTANCE_ID = "astropy__astropy-13033"


def local_context():
    return {
        "function_code_before_patch": "def example():\n    return 1",
        "function_parameters_before_patch": "{}",
        "line": "The return statement",
        "choices": ["value == 1", "value == 2"],
        "before_or_after": "after",
    }


def write_effect_pair(
    root,
    *,
    stem="local_effect",
    submission_id="test-agent",
    context=None,
    ground_truths=None,
):
    context_dir = root / "context"
    ground_truth_dir = root / "ground_truths"
    context_dir.mkdir(parents=True)
    ground_truth_dir.mkdir(parents=True)
    filename = f"{stem}__{submission_id}.json"
    (context_dir / filename).write_text(
        json.dumps(context or {INSTANCE_ID: local_context()}),
        encoding="utf-8",
    )
    (ground_truth_dir / filename).write_text(
        json.dumps(ground_truths or {INSTANCE_ID: {"answer": ["a"]}}),
        encoding="utf-8",
    )


def test_shared_intent_artifacts_are_typed_and_normalized():
    e2e = load_task_artifacts("e2e.intent")
    local = load_task_artifacts("local.intent")

    assert len(e2e.instance_ids) == len(local.instance_ids) == 297
    assert isinstance(e2e.context[INSTANCE_ID], E2EIntentContext)
    assert isinstance(e2e.ground_truths[INSTANCE_ID], AnswerGroundTruth)
    assert e2e.ground_truths[INSTANCE_ID].answer == ["d"]
    assert isinstance(local.context[INSTANCE_ID], LocalIntentContext)
    assert isinstance(local.ground_truths[INSTANCE_ID], AnswerGroundTruth)
    assert local.ground_truths[INSTANCE_ID].answer == ["d"]


@pytest.mark.skipif(
    not HISTORICAL_ARTIFACT_ROOT.is_dir(),
    reason=(
        "requires historical effect artifacts from the research repository"
    ),
)
def test_real_historical_effect_artifacts_match_external_contract():
    e2e = load_task_artifacts(
        "e2e.effect",
        submission_id=AGENT,
        artifacts_dir=HISTORICAL_ARTIFACT_ROOT,
    )
    local = load_task_artifacts(
        "local.effect",
        submission_id=AGENT,
        artifacts_dir=HISTORICAL_ARTIFACT_ROOT,
    )

    assert len(e2e.instance_ids) == len(local.instance_ids) == 297
    assert isinstance(e2e.context[INSTANCE_ID], E2EEffectContext)
    assert isinstance(e2e.ground_truths[INSTANCE_ID], E2EEffectGroundTruth)
    assert e2e.ground_truths[INSTANCE_ID].before_answer == "c"
    assert e2e.ground_truths[INSTANCE_ID].after_answer == "e"
    assert isinstance(local.context[INSTANCE_ID], LocalEffectContext)
    assert isinstance(local.ground_truths[INSTANCE_ID], AnswerGroundTruth)


def test_effect_loader_accepts_temporary_staged_pair(tmp_path):
    write_effect_pair(tmp_path)

    artifacts = load_task_artifacts(
        TaskName.LOCAL_EFFECT,
        submission_id="test-agent",
        artifacts_dir=tmp_path,
    )

    assert artifacts.instance_ids == {INSTANCE_ID}
    assert artifacts.context_source.endswith("local_effect__test-agent.json")
    assert artifacts.ground_truths[INSTANCE_ID].answer == ["a"]


def test_effect_loader_requires_external_directory():
    with pytest.raises(ArtifactResolutionError, match="--artifacts-dir"):
        load_task_artifacts("local.effect", submission_id="test-agent")


def test_effect_loader_reports_all_missing_paths(tmp_path):
    with pytest.raises(ArtifactResolutionError) as caught:
        load_task_artifacts(
            "e2e.effect",
            submission_id="test-agent",
            artifacts_dir=tmp_path,
        )

    message = str(caught.value)
    assert "context/e2e_effect__test-agent.json" in message
    assert "ground_truths/e2e_effect__test-agent.json" in message


def test_effect_loader_rejects_unsafe_submission_id(tmp_path):
    with pytest.raises(ArtifactResolutionError, match="submission_id"):
        load_task_artifacts(
            "local.effect",
            submission_id="../agent",
            artifacts_dir=tmp_path,
        )


def test_effect_loader_rejects_context_ground_truth_mismatch(tmp_path):
    write_effect_pair(
        tmp_path,
        context={INSTANCE_ID: local_context()},
        ground_truths={SECOND_INSTANCE_ID: {"answer": ["a"]}},
    )

    with pytest.raises(ArtifactValidationError, match="IDs differ"):
        load_task_artifacts(
            "local.effect",
            submission_id="test-agent",
            artifacts_dir=tmp_path,
        )


def test_effect_loader_rejects_malformed_context(tmp_path):
    invalid = local_context()
    invalid["before_or_after"] = "during"
    write_effect_pair(tmp_path, context={INSTANCE_ID: invalid})

    with pytest.raises(ArtifactValidationError, match="before_or_after"):
        load_task_artifacts(
            "local.effect",
            submission_id="test-agent",
            artifacts_dir=tmp_path,
        )


def test_effect_loader_rejects_answer_outside_available_choices(tmp_path):
    write_effect_pair(
        tmp_path,
        ground_truths={INSTANCE_ID: {"answer": ["c"]}},
    )

    with pytest.raises(ArtifactValidationError, match="outside the 2 available"):
        load_task_artifacts(
            "local.effect",
            submission_id="test-agent",
            artifacts_dir=tmp_path,
        )
