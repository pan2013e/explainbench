import json

import pytest
from pydantic import ValidationError

from explainbench.schemas import Submission, SubmissionInstance
from explainbench.submission import (
    SubmissionValidationError,
    ValidationProfile,
    is_basic_unified_diff,
    load_submission,
    supported_instance_ids,
)


INSTANCE_ID = "astropy__astropy-12907"
VALID_PATCH = """\
diff --git a/example.py b/example.py
index 1111111..2222222 100644
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old
+new
"""


def write_submission(tmp_path, **overrides):
    data = {
        "submission_id": "test-agent",
        "instances": [
            {
                "instance_id": INSTANCE_ID,
                "explanation": "This changes the return value.",
            }
        ],
    }
    data.update(overrides)
    path = tmp_path / "submission.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_models_reject_type_coercion_and_unknown_fields():
    with pytest.raises(ValidationError, match="string_type"):
        SubmissionInstance(instance_id=123, explanation="explanation")

    with pytest.raises(ValidationError, match="extra_forbidden"):
        SubmissionInstance(
            instance_id=INSTANCE_ID,
            explanation="explanation",
            typo="unexpected",
        )


@pytest.mark.parametrize("field", ["submission_id", "explanation", "instance_id"])
def test_models_reject_blank_required_strings(field):
    data = {
        "submission_id": "test-agent",
        "instances": [
            {"instance_id": INSTANCE_ID, "explanation": "explanation"}
        ],
    }
    if field == "submission_id":
        data[field] = "  "
    else:
        data["instances"][0][field] = "  "

    with pytest.raises(ValidationError, match="must be a nonempty string"):
        Submission.model_validate(data)


def test_models_reject_empty_and_duplicate_instances():
    with pytest.raises(ValidationError, match="at least one instance"):
        Submission(submission_id="test-agent", instances=[])

    instance = SubmissionInstance(
        instance_id=INSTANCE_ID,
        explanation="explanation",
    )
    with pytest.raises(ValidationError, match="duplicate instance_id"):
        Submission(submission_id="test-agent", instances=[instance, instance])


def test_supported_ids_are_packaged_from_local_intent_dataset():
    benchmark_ids = supported_instance_ids()

    assert len(benchmark_ids) == 297
    assert INSTANCE_ID in benchmark_ids


def test_base_profile_accepts_an_omitted_patch(tmp_path):
    submission = load_submission(write_submission(tmp_path))

    assert submission.instances[0].model_patch is None


def test_nonempty_patch_must_be_a_unified_diff(tmp_path):
    path = write_submission(
        tmp_path,
        instances=[
            {
                "instance_id": INSTANCE_ID,
                "explanation": "explanation",
                "model_patch": "not a diff",
            }
        ],
    )

    with pytest.raises(SubmissionValidationError) as caught:
        load_submission(path)

    assert str(caught.value.issues[0]) == (
        "instances[0].model_patch: must be a git-style unified diff"
    )


def test_patch_profiles_require_nonempty_patches(tmp_path):
    path = write_submission(tmp_path)

    for profile in (
        ValidationProfile.QUESTION_BUILDER_LOCAL,
        ValidationProfile.FULL,
    ):
        with pytest.raises(SubmissionValidationError, match="nonempty patch"):
            load_submission(path, profile=profile)


def test_lite_profile_accepts_empty_patch(tmp_path):
    path = write_submission(
        tmp_path,
        instances=[
            {
                "instance_id": INSTANCE_ID,
                "explanation": "explanation",
                "model_patch": "",
            }
        ],
    )

    load_submission(path, profile=ValidationProfile.LITE)


def test_valid_unified_diff_is_accepted_by_full_profile(tmp_path):
    path = write_submission(
        tmp_path,
        instances=[
            {
                "instance_id": INSTANCE_ID,
                "explanation": "explanation",
                "model_patch": VALID_PATCH,
            }
        ],
    )

    submission = load_submission(path, profile=ValidationProfile.FULL)

    assert is_basic_unified_diff(submission.instances[0].model_patch)


def test_unified_diff_accepts_crlf_line_endings():
    assert is_basic_unified_diff(VALID_PATCH.replace("\n", "\r\n"))


def test_unsupported_benchmark_id_has_instance_location(tmp_path):
    path = write_submission(
        tmp_path,
        instances=[
            {
                "instance_id": "unknown__project-1",
                "explanation": "explanation",
            }
        ],
    )

    with pytest.raises(SubmissionValidationError) as caught:
        load_submission(path)

    assert str(caught.value.issues[0]) == (
        "instances[0].instance_id: unsupported ExplainBench instance "
        "'unknown__project-1'"
    )


def test_invalid_json_reports_line_and_column(tmp_path):
    path = tmp_path / "submission.json"
    path.write_text('{\n  "submission_id":\n}', encoding="utf-8")

    with pytest.raises(SubmissionValidationError) as caught:
        load_submission(path)

    assert "line 3, column 1" in str(caught.value)


def test_duplicate_json_fields_are_rejected(tmp_path):
    path = tmp_path / "submission.json"
    path.write_text(
        '{"submission_id":"first","submission_id":"second","instances":[]}',
        encoding="utf-8",
    )

    with pytest.raises(SubmissionValidationError, match="duplicate JSON field"):
        load_submission(path)


def test_structural_errors_have_readable_locations(tmp_path):
    path = write_submission(
        tmp_path,
        instances=[{"instance_id": INSTANCE_ID, "explanationn": "typo"}],
    )

    with pytest.raises(SubmissionValidationError) as caught:
        load_submission(path)

    messages = {str(issue) for issue in caught.value.issues}
    assert "instances[0].explanation: Field required" in messages
    assert "instances[0].explanationn: Extra inputs are not permitted" in messages
