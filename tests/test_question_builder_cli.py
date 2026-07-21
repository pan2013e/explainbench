import json

from pathlib import Path

from explainbench import cli
from explainbench.question_builders.local.registry import LOCAL_STAGE_REGISTRY
from explainbench.question_builders.local import runners


INSTANCE_ID = "astropy__astropy-12907"
PATCH = """\
diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old
+new
"""


def write_submission(tmp_path):
    path = tmp_path / "submission.json"
    path.write_text(
        json.dumps(
            {
                "submission_id": "test-agent",
                "instances": [
                    {
                        "instance_id": INSTANCE_ID,
                        "model_patch": PATCH,
                        "explanation": "The patch changes the returned value.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def install_fake_identify(monkeypatch):
    def option(arguments, name):
        return arguments[arguments.index(name) + 1]

    def fake_identify(module, arguments, context, **kwargs):
        arguments = tuple(arguments)
        if module == runners.IDENTIFY_PATCHED_FUNCTIONS_MODULE:
            Path(option(arguments, "--output-path")).write_text(
                json.dumps(
                    {
                        context.submission_id: {
                            context.instance.instance_id: ["example:changed"]
                        }
                    }
                ),
                encoding="utf-8",
            )
            return
        if module == runners.TRACK_TEST_CALLS_MODULE:
            tracking_root = (
                Path(option(arguments, "--work-dir"))
                / "logs/run_evaluation"
                / option(arguments, "--run-id")
                / context.submission_id
                / context.instance.instance_id
            )
            for name in ("buggy_traces", "patched_traces"):
                directory = tracking_root / name
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "test.jsonl").write_text(
                    "{}\n",
                    encoding="utf-8",
                )
            return
        assert module == runners.SELECT_TRACE_FUNCTIONS_MODULE
        Path(option(arguments, "--output-path")).write_text(
            json.dumps(
                {
                    context.submission_id: {
                        context.instance.instance_id: ["example:called"]
                    }
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(runners, "run_canonical_module", fake_identify)


def test_stages_lists_meaningful_names_in_dependency_order(capsys):
    status = cli.main(["question-builder", "local", "stages"])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert len(lines) == 10
    assert "identify-patched-functions" in lines[0]
    assert "export-question-artifacts" in lines[-1]


def test_pending_stage_fails_explicitly_and_status_is_inspectable(
    tmp_path,
    capsys,
    monkeypatch,
):
    install_fake_identify(monkeypatch)
    submission = write_submission(tmp_path)
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"

    status = cli.main(
        [
            "question-builder",
            "local",
            "run",
            str(submission),
            "--workspace",
            str(workspace),
            "--output",
            str(artifacts),
        ]
    )
    run_output = capsys.readouterr()

    assert status == 1
    assert "stage_not_connected" not in run_output.err
    assert "checkpoints and logs were retained" in run_output.err
    assert "identify-patched-functions" in run_output.out
    assert (workspace / "manifest.json").is_file()

    status = cli.main(
        [
            "question-builder",
            "local",
            "status",
            "--workspace",
            str(workspace),
        ]
    )
    status_output = capsys.readouterr()

    assert status == 0
    assert "Submission ID: test-agent" in status_output.out
    assert "stage 'trace-program-state' is not yet connected" in (
        status_output.out
    )
    assert "retryable=no" in status_output.out
    assert "retry_cycle=1" in status_output.out
    assert "cycle_attempt=1" in status_output.out
    assert "total_attempts=1" in status_output.out
    assert "Artifacts: not exported" in status_output.out


def test_individual_later_stage_reports_missing_prerequisite(tmp_path, capsys):
    submission = write_submission(tmp_path)

    status = cli.main(
        [
            "question-builder",
            "local",
            "stage",
            "find-first-divergence",
            str(submission),
            "--workspace",
            str(tmp_path / "workspace"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "requires compatible results" in captured.err
    assert "question-builder local run" in captured.err


def test_local_builder_config_paths_are_relative_to_config(
    tmp_path,
    capsys,
    monkeypatch,
):
    install_fake_identify(monkeypatch)
    submission = write_submission(tmp_path)
    config = tmp_path / "builder.toml"
    config.write_text(
        """\
schema_version = 1

[execution]
workers = 2
max_attempts = 4
identify_timeout_seconds = 123
track_test_timeout_seconds = 456
track_command_timeout_seconds = 789
select_trace_timeout_seconds = 234

[models]
candidate_generation = "test-model"

[paths]
workspace = "configured-workspace"
output = "configured-artifacts"
repository_cache = "configured-repositories"

[benchmark]
dataset_name = "example/dataset"
repository_remote = "https://example.invalid"
""",
        encoding="utf-8",
    )

    status = cli.main(
        [
            "question-builder",
            "local",
            "run",
            str(submission),
            "--config",
            str(config),
        ]
    )

    capsys.readouterr()
    assert status == 1
    assert (tmp_path / "configured-workspace" / "manifest.json").is_file()
    assert (tmp_path / "configured-workspace" / "input/predictions.json").is_file()


def test_local_registry_has_the_documented_stage_names():
    assert LOCAL_STAGE_REGISTRY.names == (
        "identify-patched-functions",
        "track-test-calls",
        "select-trace-functions",
        "trace-program-state",
        "find-first-divergence",
        "generate-candidate-expressions",
        "execute-candidate-expressions",
        "validate-candidate-expressions",
        "build-answer-choices",
        "export-question-artifacts",
    )
