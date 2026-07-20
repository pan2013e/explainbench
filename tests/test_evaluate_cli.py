import json

import pytest

from explainbench import cli
from explainbench.evaluation import service
from explainbench.evaluation.checkpoints import checkpoint_path_for_output


INSTANCE_ID = "astropy__astropy-12907"
VALID_PATCH = """\
diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old
+new
"""


class FakeEvaluator:
    last_sampling_params = None

    def __init__(self, model_id, **sampling_params):
        self.model_id = model_id
        self.num_generations = sampling_params["n"]
        type(self).last_sampling_params = sampling_params
        self.token_usage = {
            "completion_tokens": 2,
            "prompt_tokens": 10,
            "total_tokens": 12,
        }

    def infer(self, messages, schema):
        if "before_selection" in schema.model_fields:
            payload = {"before_selection": "a", "after_selection": "a"}
        else:
            payload = {"answer": ["d"]}
        return [
            schema.model_validate(payload) for _ in range(self.num_generations)
        ]


class InterruptingEvaluator(FakeEvaluator):
    calls = 0

    def infer(self, messages, schema):
        type(self).calls += 1
        if type(self).calls == 2:
            raise KeyboardInterrupt
        return super().infer(messages, schema)


class CountingEvaluator(FakeEvaluator):
    calls = 0

    def infer(self, messages, schema):
        type(self).calls += 1
        return super().infer(messages, schema)


def write_submission(tmp_path, *, submission_id="test-agent", with_patch=False):
    submission = tmp_path / "submission.json"
    instance = {
        "instance_id": INSTANCE_ID,
        "explanation": "The relevant answer is described by option d.",
    }
    if with_patch:
        instance["model_patch"] = VALID_PATCH
    submission.write_text(
        json.dumps(
            {
                "submission_id": submission_id,
                "instances": [instance],
            }
        ),
        encoding="utf-8",
    )
    return submission


def write_effect_artifacts(root, submission_id):
    context_dir = root / "context"
    ground_truth_dir = root / "ground_truths"
    context_dir.mkdir(parents=True)
    ground_truth_dir.mkdir(parents=True)
    contexts = {
        "e2e_effect": {
            "test_content": "assert example() == 2",
            "choices": ["passes", "fails"],
        },
        "local_effect": {
            "function_code_before_patch": "def example():\n    return 1",
            "function_parameters_before_patch": "{}",
            "line": "return 1",
            "choices": ["return value", "exception"],
            "before_or_after": "after",
        },
    }
    ground_truths = {
        "e2e_effect": {"before_answer": "a", "after_answer": "a"},
        "local_effect": {"answer": ["a"]},
    }
    for task, context in contexts.items():
        filename = f"{task}__{submission_id}.json"
        (context_dir / filename).write_text(
            json.dumps({INSTANCE_ID: context}),
            encoding="utf-8",
        )
        (ground_truth_dir / filename).write_text(
            json.dumps({INSTANCE_ID: ground_truths[task]}),
            encoding="utf-8",
        )


def test_evaluate_lite_writes_versioned_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(service, "Model", FakeEvaluator)
    submission = write_submission(tmp_path)
    output = tmp_path / "results" / "lite.json"

    status = cli.main(
        [
            "evaluate",
            str(submission),
            "--mode",
            "lite",
            "--model",
            "test-model",
            "--num-generations",
            "2",
            "--workers",
            "2",
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    result = json.loads(output.read_text(encoding="utf-8"))
    assert status == 0
    assert captured.err == ""
    assert not checkpoint_path_for_output(output).exists()
    assert "Evaluation complete" in captured.out
    assert "Preparing 1 submission instance(s)" in captured.out
    assert "Output:" in captured.out
    assert "Validating submission and artifacts" in captured.out
    assert result["schema_version"] == 1
    assert result["selection"] == {
        "mode": "lite",
        "tasks": ["e2e.intent", "local.intent"],
    }
    assert result["evaluator"] == {
        "model": "test-model",
        "num_generations": 2,
        "instance_workers": 2,
        "generation_workers": 10,
        "temperature": 1.0,
        "top_p": 1.0,
        "max_tokens": 8192,
        "max_retries": 5,
        "token_usage": {
            "completion_tokens": 2,
            "prompt_tokens": 10,
            "total_tokens": 12,
        },
    }
    for task in result["tasks"].values():
        assert task["counts"] == {
            "submitted": 1,
            "evaluated": 1,
            "skipped": 0,
            "failed": 0,
        }
        assert task["statistics"] == {"mean": 1.0, "sem": None}
        assert task["instances"][INSTANCE_ID]["scores"] == [1.0, 1.0]


def test_evaluate_full_uses_staged_effect_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "Model", FakeEvaluator)
    submission_id = "test-agent"
    submission = write_submission(
        tmp_path,
        submission_id=submission_id,
        with_patch=True,
    )
    artifacts = tmp_path / "question-artifacts"
    write_effect_artifacts(artifacts, submission_id)
    output = tmp_path / "full.json"

    status = cli.main(
        [
            "evaluate",
            str(submission),
            "--mode",
            "full",
            "--artifacts-dir",
            str(artifacts),
            "--num-generations",
            "1",
            "--output",
            str(output),
        ]
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert status == 0
    assert result["selection"]["tasks"] == [
        "e2e.intent",
        "e2e.effect",
        "local.intent",
        "local.effect",
    ]
    assert result["tasks"]["e2e.effect"]["instances"][INSTANCE_ID][
        "predictions"
    ] == [{"before_selection": "a", "after_selection": "a"}]
    assert result["tasks"]["local.effect"]["counts"]["evaluated"] == 1


def test_evaluate_supports_repeatable_fine_grained_tasks(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(service, "Model", FakeEvaluator)
    submission_id = "test-agent"
    submission = write_submission(
        tmp_path,
        submission_id=submission_id,
        with_patch=True,
    )
    artifacts = tmp_path / "question-artifacts"
    write_effect_artifacts(artifacts, submission_id)
    output = tmp_path / "selected.json"

    status = cli.main(
        [
            "evaluate",
            str(submission),
            "--task",
            "local.intent",
            "--task",
            "e2e.effect",
            "--artifacts-dir",
            str(artifacts),
            "--num-generations",
            "1",
            "--output",
            str(output),
        ]
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert status == 0
    assert result["selection"] == {
        "mode": None,
        "tasks": ["local.intent", "e2e.effect"],
    }
    assert set(result["tasks"]) == {"local.intent", "e2e.effect"}


def test_effect_preflight_fails_before_model_construction(
    tmp_path,
    monkeypatch,
    capsys,
):
    class ForbiddenEvaluator:
        def __init__(self, *args, **kwargs):
            raise AssertionError("model must not be constructed")

    monkeypatch.setattr(service, "Model", ForbiddenEvaluator)
    submission = write_submission(tmp_path, with_patch=True)
    output = tmp_path / "should-not-exist.json"

    status = cli.main(
        [
            "evaluate",
            str(submission),
            "--task",
            "local.effect",
            "--artifacts-dir",
            str(tmp_path / "missing-artifacts"),
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "missing required artifacts" in captured.err
    assert not output.exists()


def test_evaluate_rejects_mode_and_task_together(tmp_path):
    submission = write_submission(tmp_path)

    with pytest.raises(SystemExit, match="2"):
        cli.main(
            [
                "evaluate",
                str(submission),
                "--mode",
                "lite",
                "--task",
                "local.intent",
                "--output",
                str(tmp_path / "result.json"),
            ]
        )


def test_evaluate_can_be_fully_configured_by_toml(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(service, "Model", FakeEvaluator)
    submission = write_submission(tmp_path)
    config = tmp_path / "evaluation.toml"
    config.write_text(
        """\
schema_version = 1

[selection]
mode = "lite"

[evaluator]
model = "configured-model"
num_generations = 3
instance_workers = 4
generation_workers = 2
temperature = 0.3
top_p = 0.7
max_tokens = 512
max_retries = 2

[paths]
output = "configured-results.json"
""",
        encoding="utf-8",
    )

    status = cli.main(
        [
            "evaluate",
            str(submission),
            "--config",
            str(config),
            "--num-generations",
            "1",
            "--temperature",
            "0.6",
        ]
    )

    output = tmp_path / "configured-results.json"
    result = json.loads(output.read_text(encoding="utf-8"))
    assert status == 0
    assert result["selection"]["mode"] == "lite"
    assert result["evaluator"] == {
        "model": "configured-model",
        "num_generations": 1,
        "instance_workers": 4,
        "generation_workers": 2,
        "temperature": 0.6,
        "top_p": 0.7,
        "max_tokens": 512,
        "max_retries": 2,
        "token_usage": {
            "completion_tokens": 2,
            "prompt_tokens": 10,
            "total_tokens": 12,
        },
    }
    assert FakeEvaluator.last_sampling_params == {
        "env_file": None,
        "max_retries": 2,
        "generation_workers": 2,
        "n": 1,
        "temperature": 0.6,
        "top_p": 0.7,
        "max_tokens": 512,
    }


def test_evaluate_resumes_completed_task_instances_after_interruption(
    tmp_path,
    monkeypatch,
    capsys,
):
    InterruptingEvaluator.calls = 0
    CountingEvaluator.calls = 0
    monkeypatch.setattr(service, "Model", InterruptingEvaluator)
    submission = write_submission(tmp_path)
    output = tmp_path / "resumed.json"
    arguments = [
        "evaluate",
        str(submission),
        "--mode",
        "lite",
        "--num-generations",
        "1",
        "--workers",
        "1",
        "--output",
        str(output),
    ]

    with pytest.raises(KeyboardInterrupt):
        cli.main(arguments)

    checkpoint = checkpoint_path_for_output(output)
    assert checkpoint.is_file()
    assert not output.exists()

    monkeypatch.setattr(service, "Model", CountingEvaluator)
    status = cli.main([*arguments, "--resume"])

    captured = capsys.readouterr()
    result = json.loads(output.read_text(encoding="utf-8"))
    assert status == 0
    assert CountingEvaluator.calls == 1
    assert "Resuming from checkpoint" in captured.out
    assert set(result["tasks"]) == {"e2e.intent", "local.intent"}
    assert all(task["counts"]["evaluated"] == 1 for task in result["tasks"].values())
    assert not checkpoint.exists()


def test_evaluate_rejects_incompatible_resume_before_model_construction(
    tmp_path,
    monkeypatch,
    capsys,
):
    InterruptingEvaluator.calls = 0
    monkeypatch.setattr(service, "Model", InterruptingEvaluator)
    submission = write_submission(tmp_path)
    output = tmp_path / "incompatible.json"
    arguments = [
        "evaluate",
        str(submission),
        "--mode",
        "lite",
        "--num-generations",
        "1",
        "--workers",
        "1",
        "--output",
        str(output),
    ]

    with pytest.raises(KeyboardInterrupt):
        cli.main(arguments)

    payload = json.loads(submission.read_text(encoding="utf-8"))
    payload["instances"][0]["explanation"] = "A changed explanation."
    submission.write_text(json.dumps(payload), encoding="utf-8")

    class ForbiddenEvaluator:
        def __init__(self, *args, **kwargs):
            raise AssertionError("model must not be constructed")

    monkeypatch.setattr(service, "Model", ForbiddenEvaluator)
    status = cli.main([*arguments, "--resume"])

    captured = capsys.readouterr()
    assert status == 1
    assert "checkpoint does not match" in captured.err
    assert checkpoint_path_for_output(output).is_file()
    assert not output.exists()


def test_evaluate_retains_checkpoint_for_failed_instances_and_retries_them(
    tmp_path,
    monkeypatch,
    capsys,
):
    class PartiallyFailingEvaluator(FakeEvaluator):
        def infer(self, messages, schema):
            if isinstance(messages, str) and "Masked Test:" in messages:
                raise RuntimeError("simulated provider failure")
            return super().infer(messages, schema)

    CountingEvaluator.calls = 0
    monkeypatch.setattr(service, "Model", PartiallyFailingEvaluator)
    submission = write_submission(tmp_path)
    output = tmp_path / "retry.json"
    arguments = [
        "evaluate",
        str(submission),
        "--mode",
        "lite",
        "--num-generations",
        "1",
        "--workers",
        "1",
        "--output",
        str(output),
    ]

    status = cli.main(arguments)

    checkpoint = checkpoint_path_for_output(output)
    first_result = json.loads(output.read_text(encoding="utf-8"))
    assert status == 0
    assert first_result["tasks"]["e2e.intent"]["counts"]["failed"] == 1
    assert checkpoint.is_file()
    assert "Checkpoint retained for retry" in capsys.readouterr().out

    monkeypatch.setattr(service, "Model", CountingEvaluator)
    status = cli.main([*arguments, "--resume"])

    resumed_result = json.loads(output.read_text(encoding="utf-8"))
    assert status == 0
    assert CountingEvaluator.calls == 1
    assert all(
        task["counts"]["failed"] == 0
        for task in resumed_result["tasks"].values()
    )
    assert not checkpoint.exists()
