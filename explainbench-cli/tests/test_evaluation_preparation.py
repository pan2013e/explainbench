import json

import pytest

from explainbench.evaluation.preparation import (
    EvaluationPreparationError,
    prepare_evaluation,
)
from explainbench.evaluation.registry import TaskName, resolve_task_selection
from explainbench.schemas import Submission
from explainbench.submission import SubmissionValidationError


INSTANCE_ID = "astropy__astropy-12907"
SECOND_INSTANCE_ID = "astropy__astropy-13033"
VALID_PATCH = """\
diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old
+new
"""


def make_submission(*instance_ids, with_patches=False):
    return Submission.model_validate(
        {
            "submission_id": "test-agent",
            "instances": [
                {
                    "instance_id": instance_id,
                    "explanation": f"Explanation for {instance_id}",
                    **({"model_patch": VALID_PATCH} if with_patches else {}),
                }
                for instance_id in instance_ids
            ],
        }
    )


def write_local_effect_pair(root, instance_ids):
    context_dir = root / "context"
    ground_truth_dir = root / "ground_truths"
    context_dir.mkdir(parents=True)
    ground_truth_dir.mkdir(parents=True)
    filename = "local_effect__test-agent.json"
    context = {
        instance_id: {
            "function_code_before_patch": "def example():\n    return 1",
            "function_parameters_before_patch": "{}",
            "line": "The return statement",
            "choices": ["value == 1", "value == 2"],
            "before_or_after": "after",
        }
        for instance_id in instance_ids
    }
    ground_truths = {
        instance_id: {"answer": ["a"]} for instance_id in instance_ids
    }
    (context_dir / filename).write_text(json.dumps(context), encoding="utf-8")
    (ground_truth_dir / filename).write_text(
        json.dumps(ground_truths),
        encoding="utf-8",
    )


def test_prepare_lite_uses_packaged_intents_without_patches():
    submission = make_submission(INSTANCE_ID, SECOND_INSTANCE_ID)
    selection = resolve_task_selection(mode="lite")

    prepared = prepare_evaluation(submission, selection)

    assert tuple(prepared.tasks) == (TaskName.E2E_INTENT, TaskName.LOCAL_INTENT)
    assert all(
        task.evaluable_instance_ids == (INSTANCE_ID, SECOND_INSTANCE_ID)
        for task in prepared.tasks.values()
    )
    assert all(not task.missing_instance_ids for task in prepared.tasks.values())


def test_prepare_effect_selection_requires_patches_before_artifacts(tmp_path):
    submission = make_submission(INSTANCE_ID)
    selection = resolve_task_selection(tasks=["local.effect"])

    with pytest.raises(SubmissionValidationError, match="nonempty patch"):
        prepare_evaluation(submission, selection, artifacts_dir=tmp_path)


def test_prepare_effect_reports_evaluable_and_missing_instances(tmp_path):
    write_local_effect_pair(tmp_path, [INSTANCE_ID])
    submission = make_submission(
        INSTANCE_ID,
        SECOND_INSTANCE_ID,
        with_patches=True,
    )
    selection = resolve_task_selection(tasks=["local.effect"])

    prepared = prepare_evaluation(submission, selection, artifacts_dir=tmp_path)
    task = prepared.tasks[TaskName.LOCAL_EFFECT]

    assert task.evaluable_instance_ids == (INSTANCE_ID,)
    assert task.missing_instance_ids == (SECOND_INSTANCE_ID,)


def test_prepare_rejects_task_with_no_evaluable_instances(tmp_path):
    write_local_effect_pair(tmp_path, [INSTANCE_ID])
    submission = make_submission(SECOND_INSTANCE_ID, with_patches=True)
    selection = resolve_task_selection(tasks=["local.effect"])

    with pytest.raises(EvaluationPreparationError, match="no artifacts"):
        prepare_evaluation(submission, selection, artifacts_dir=tmp_path)
