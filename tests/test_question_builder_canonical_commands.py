import json
import sys

from pathlib import Path
from types import SimpleNamespace

import pytest

from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
)
from explainbench.question_builders.common.subprocess_runner import run_command
from explainbench.question_builders.local import runners
from explainbench.question_builders.local.config import LocalBuilderConfig
from explainbench.question_builders.local.registry import LOCAL_STAGE_REGISTRY
from explainbench.question_builders.local.service import run_local_stage
from explainbench.question_builders.local.submission_adapter import (
    SubmissionAdapterError,
    build_predictions_payload,
)
from explainbench.question_builders.local.workspace import LocalBuilderWorkspace
from explainbench.schemas import Submission


INSTANCE_ID = "astropy__astropy-12907"
PATCH = """\
diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old
+new
"""


def make_submission(*, patch=PATCH):
    return Submission.model_validate(
        {
            "submission_id": "test-agent",
            "instances": [
                {
                    "instance_id": INSTANCE_ID,
                    "explanation": "The patch changes the example.",
                    "model_patch": patch,
                }
            ],
        }
    )


def make_context(tmp_path):
    instance = make_submission().instances[0]
    attempt_directory = tmp_path / "work" / "attempt-1"
    log_directory = tmp_path / "logs" / "attempt-1"
    return StageContext(
        submission_id="test-agent",
        instance=instance,
        workspace=tmp_path,
        work_directory=tmp_path / "work",
        attempt_directory=attempt_directory,
        log_directory=log_directory,
        retry_cycle=1,
        cycle_attempt=1,
        total_attempt=1,
        upstream_results={},
        config=SimpleNamespace(),
    )


def test_submission_adapter_produces_canonical_predictions():
    payload = build_predictions_payload(make_submission())

    assert payload == {
        INSTANCE_ID: {
            "instance_id": INSTANCE_ID,
            "model_patch": PATCH,
            "model_name_or_path": "test-agent",
        }
    }


def test_submission_adapter_rejects_missing_patch():
    with pytest.raises(SubmissionAdapterError, match="does not contain a patch"):
        build_predictions_payload(make_submission(patch=None))


def test_subprocess_runner_records_stdout_stderr_and_command(tmp_path):
    context = make_context(tmp_path)

    result = run_command(
        (
            sys.executable,
            "-c",
            "import sys; print('output'); print('error', file=sys.stderr)",
        ),
        context,
        timeout=10,
    )

    assert result.return_code == 0
    assert result.stdout_path.read_text(encoding="utf-8").strip() == "output"
    assert result.stderr_path.read_text(encoding="utf-8").strip() == "error"
    command_record = json.loads(
        (context.attempt_directory / "command.json").read_text(encoding="utf-8")
    )
    assert command_record["state"] == "completed"
    assert command_record["return_code"] == 0


def test_subprocess_runner_classifies_nonzero_exit(tmp_path):
    context = make_context(tmp_path)

    with pytest.raises(StageExecutionError) as captured:
        run_command(
            (sys.executable, "-c", "raise SystemExit(7)"),
            context,
            timeout=10,
            retryable_nonzero=True,
        )

    assert captured.value.category == "canonical_command_failed"
    assert captured.value.retryable is True
    command_record = json.loads(
        (context.attempt_directory / "command.json").read_text(encoding="utf-8")
    )
    assert command_record["state"] == "failed"
    assert command_record["return_code"] == 7


def test_subprocess_runner_terminates_timed_out_process(tmp_path):
    context = make_context(tmp_path)

    with pytest.raises(StageExecutionError) as captured:
        run_command(
            (sys.executable, "-c", "import time; time.sleep(30)"),
            context,
            timeout=1,
        )

    assert captured.value.category == "canonical_command_timeout"
    assert captured.value.retryable is True
    command_record = json.loads(
        (context.attempt_directory / "command.json").read_text(encoding="utf-8")
    )
    assert command_record["state"] == "timed_out"
    assert isinstance(command_record["return_code"], int)


def test_identify_stage_uses_adapter_and_reuses_checkpoint(
    tmp_path,
    monkeypatch,
):
    calls = []

    def fake_command(module, arguments, context, **kwargs):
        calls.append((module, tuple(arguments), kwargs))
        options = dict(zip(arguments[::2], arguments[1::2]))
        Path(options["--output-path"]).write_text(
            json.dumps(
                {
                    context.submission_id: {
                        context.instance.instance_id: [
                            "example:Changed.function"
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(runners, "run_canonical_module", fake_command)
    config = LocalBuilderConfig(
        workspace=tmp_path / "workspace",
        artifact_output=None,
        max_workers=1,
        max_attempts=2,
        candidate_generation_model="candidate-model",
        repository_cache=tmp_path / "repositories",
        dataset_name="example/dataset",
        repository_remote="https://example.invalid",
        identify_timeout_seconds=123,
    )
    submission = make_submission()

    initial = run_local_stage(
        "identify-patched-functions",
        submission,
        config,
        registry=LOCAL_STAGE_REGISTRY,
    )
    resumed = run_local_stage(
        "identify-patched-functions",
        submission,
        config,
        registry=LOCAL_STAGE_REGISTRY,
        resume=True,
    )

    assert initial.completed == 1
    assert resumed.reused == 1
    assert len(calls) == 1
    module, arguments, keywords = calls[0]
    assert module == runners.IDENTIFY_PATCHED_FUNCTIONS_MODULE
    options = dict(zip(arguments[::2], arguments[1::2]))
    assert options["--agent"] == "test-agent"
    assert options["--instance-ids"] == INSTANCE_ID
    assert options["--repos-root"] == str(
        tmp_path / "repositories" / INSTANCE_ID
    )
    assert options["--dataset-name"] == "example/dataset"
    assert options["--repository-remote"] == "https://example.invalid"
    assert keywords["timeout"] == 123

    predictions = json.loads(
        (config.workspace / "input" / "predictions.json").read_text(
            encoding="utf-8"
        )
    )
    assert predictions[INSTANCE_ID]["model_patch"] == PATCH
    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    result = workspace.read_result("identify-patched-functions", INSTANCE_ID)
    assert result.data == {
        "instance_id": INSTANCE_ID,
        "qualnames": ["example:Changed.function"],
    }


def _argument_value(arguments, option):
    index = arguments.index(option)
    return arguments[index + 1]


def test_track_stage_builds_manifest_and_reuses_valid_artifacts(
    tmp_path,
    monkeypatch,
):
    calls = []

    def fake_command(module, arguments, context, **kwargs):
        arguments = tuple(arguments)
        calls.append((module, arguments, kwargs))
        if module == runners.IDENTIFY_PATCHED_FUNCTIONS_MODULE:
            Path(_argument_value(arguments, "--output-path")).write_text(
                json.dumps(
                    {
                        context.submission_id: {
                            context.instance.instance_id: [
                                "example:Changed.function"
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            return
        assert module == runners.TRACK_TEST_CALLS_MODULE
        tracking_root = (
            Path(_argument_value(arguments, "--work-dir"))
            / "logs"
            / "run_evaluation"
            / _argument_value(arguments, "--run-id")
            / context.submission_id
            / context.instance.instance_id
        )
        for name in ("buggy_traces", "patched_traces"):
            directory = tracking_root / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "test_case.jsonl").write_text(
                '{"target":"example:Changed.function","stack":[]}\n',
                encoding="utf-8",
            )

    monkeypatch.setattr(runners, "run_canonical_module", fake_command)
    config = LocalBuilderConfig(
        workspace=tmp_path / "workspace",
        artifact_output=None,
        max_workers=1,
        max_attempts=2,
        candidate_generation_model="candidate-model",
        dataset_name="example/dataset",
        track_test_timeout_seconds=321,
        track_command_timeout_seconds=987,
    )
    submission = make_submission()

    identify = run_local_stage(
        "identify-patched-functions",
        submission,
        config,
    )
    tracked = run_local_stage(
        "track-test-calls",
        submission,
        config,
        resume=True,
    )
    resumed = run_local_stage(
        "track-test-calls",
        submission,
        config,
        resume=True,
    )

    assert identify.completed == 1
    assert tracked.completed == 1
    assert resumed.reused == 1
    assert [item[0] for item in calls] == [
        runners.IDENTIFY_PATCHED_FUNCTIONS_MODULE,
        runners.TRACK_TEST_CALLS_MODULE,
    ]
    _, arguments, keywords = calls[1]
    assert _argument_value(arguments, "--agent") == "test-agent"
    assert _argument_value(arguments, "--instance-ids") == INSTANCE_ID
    assert _argument_value(arguments, "--max-workers") == "1"
    assert _argument_value(arguments, "--timeout") == "321"
    assert _argument_value(arguments, "--dataset-name") == "example/dataset"
    assert "--no-force-rebuild" in arguments
    assert "--no-clean" in arguments
    assert keywords["timeout"] == 987

    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    result = workspace.read_result("track-test-calls", INSTANCE_ID)
    manifest = result.data["artifact_manifest"]
    paths = {item["path"] for item in manifest["files"]}
    assert paths == {
        "buggy_traces/test_case.jsonl",
        "patched_traces/test_case.jsonl",
    }


def test_track_stage_reruns_when_a_manifest_artifact_changes(
    tmp_path,
    monkeypatch,
):
    track_calls = []

    def fake_command(module, arguments, context, **kwargs):
        arguments = tuple(arguments)
        if module == runners.IDENTIFY_PATCHED_FUNCTIONS_MODULE:
            Path(_argument_value(arguments, "--output-path")).write_text(
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
        track_calls.append(arguments)
        tracking_root = (
            Path(_argument_value(arguments, "--work-dir"))
            / "logs/run_evaluation"
            / _argument_value(arguments, "--run-id")
            / context.submission_id
            / context.instance.instance_id
        )
        for name in ("buggy_traces", "patched_traces"):
            directory = tracking_root / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "test.jsonl").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(runners, "run_canonical_module", fake_command)
    config = LocalBuilderConfig(
        workspace=tmp_path / "workspace",
        artifact_output=None,
        max_workers=1,
        max_attempts=1,
        candidate_generation_model="candidate-model",
    )
    submission = make_submission()
    run_local_stage("identify-patched-functions", submission, config)
    run_local_stage("track-test-calls", submission, config, resume=True)
    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    first_result = workspace.read_result("track-test-calls", INSTANCE_ID)
    first_manifest = first_result.data["artifact_manifest"]
    stage_instance = (
        config.workspace / "stages" / "track-test-calls" / "instances" / INSTANCE_ID
    )
    corrupt_path = (
        stage_instance
        / first_manifest["root"]
        / first_manifest["files"][0]["path"]
    )
    corrupt_path.write_text("changed\n", encoding="utf-8")

    rerun = run_local_stage(
        "track-test-calls",
        submission,
        config,
        resume=True,
    )

    assert rerun.completed == 1
    assert len(track_calls) == 2
    status = workspace.read_status("track-test-calls", INSTANCE_ID)
    assert status.total_attempts == 2


def test_select_trace_functions_uses_tracking_artifacts_and_reuses_result(
    tmp_path,
    monkeypatch,
):
    calls = []

    def fake_command(module, arguments, context, **kwargs):
        arguments = tuple(arguments)
        calls.append((module, arguments, kwargs))
        if module == runners.IDENTIFY_PATCHED_FUNCTIONS_MODULE:
            Path(_argument_value(arguments, "--output-path")).write_text(
                json.dumps(
                    {
                        context.submission_id: {
                            context.instance.instance_id: [
                                "example:Changed.function"
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            return
        if module == runners.TRACK_TEST_CALLS_MODULE:
            tracking_root = (
                Path(_argument_value(arguments, "--work-dir"))
                / "logs/run_evaluation"
                / _argument_value(arguments, "--run-id")
                / context.submission_id
                / context.instance.instance_id
            )
            record = {
                "target": "example:Changed.function",
                "stack": [["example", "caller"], ["example", "callee"]],
            }
            for name in ("buggy_traces", "patched_traces"):
                directory = tracking_root / name
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "test.jsonl").write_text(
                    f"{json.dumps(record)}\n",
                    encoding="utf-8",
                )
            return

        assert module == runners.SELECT_TRACE_FUNCTIONS_MODULE
        targets = json.loads(
            Path(_argument_value(arguments, "--targets-json")).read_text(
                encoding="utf-8"
            )
        )
        assert targets == {
            context.submission_id: {
                context.instance.instance_id: ["example:Changed.function"]
            }
        }
        root = Path(_argument_value(arguments, "--root-path"))
        assert (root / "buggy_traces/test.jsonl").is_file()
        assert (root / "patched_traces/test.jsonl").is_file()
        Path(_argument_value(arguments, "--output-path")).write_text(
            json.dumps(
                {
                    context.submission_id: {
                        context.instance.instance_id: ["callee", "caller"]
                    }
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(runners, "run_canonical_module", fake_command)
    config = LocalBuilderConfig(
        workspace=tmp_path / "workspace",
        artifact_output=None,
        max_workers=1,
        max_attempts=1,
        candidate_generation_model="candidate-model",
        select_trace_timeout_seconds=654,
    )
    submission = make_submission()
    run_local_stage("identify-patched-functions", submission, config)
    run_local_stage("track-test-calls", submission, config, resume=True)

    selected = run_local_stage(
        "select-trace-functions",
        submission,
        config,
        resume=True,
    )
    resumed = run_local_stage(
        "select-trace-functions",
        submission,
        config,
        resume=True,
    )

    assert selected.completed == 1
    assert resumed.reused == 1
    assert [item[0] for item in calls] == [
        runners.IDENTIFY_PATCHED_FUNCTIONS_MODULE,
        runners.TRACK_TEST_CALLS_MODULE,
        runners.SELECT_TRACE_FUNCTIONS_MODULE,
    ]
    assert calls[-1][2]["timeout"] == 654
    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    result = workspace.read_result("select-trace-functions", INSTANCE_ID)
    assert result.data == {
        "instance_id": INSTANCE_ID,
        "functions": ["callee", "caller"],
    }
