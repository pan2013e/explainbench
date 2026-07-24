import json
import sys

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from dataset.extract_ground_truths.effect.paid_inference import (
    PaidInferenceJournal,
)
from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
)
from explainbench.question_builders.common.subprocess_runner import run_command
from explainbench.question_builders.common.status import StoredStageResult
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


def test_candidate_persistence_failure_disables_automatic_retry(
    tmp_path,
    monkeypatch,
):
    context = replace(
        make_context(tmp_path),
        upstream_results={
            "find-first-divergence": StoredStageResult(
                outcome="completed",
                data={
                    "instance_id": INSTANCE_ID,
                    "divergence": {
                        "file_path": "example.py",
                        "function_name": "example:changed",
                    },
                },
            )
        },
        config=SimpleNamespace(
            candidate_generation_changed_candidates=1,
            candidate_generation_unchanged_candidates=1,
            candidate_generation_instance_workers=1,
            candidate_generation_agent_workers=1,
            candidate_generation_model="test-model",
            candidate_generation_reasoning_effort="medium",
            candidate_generation_model_retries=1,
            candidate_generation_inference=True,
            candidate_generation_env_file=None,
            candidate_generation_command_timeout_seconds=60,
        ),
    )

    def fail_after_paid_response(module, arguments, context, **kwargs):
        assert module == runners.BUILD_STEP2_MODULE
        context.attempt_directory.mkdir(parents=True, exist_ok=True)
        (context.attempt_directory / "command.json").write_text(
            json.dumps(
                {
                    "return_code": runners.PERSISTENCE_FAILURE_EXIT_CODE,
                }
            ),
            encoding="utf-8",
        )
        raise StageExecutionError(
            "canonical command failed",
            category="canonical_command_failed",
            retryable=True,
        )

    monkeypatch.setattr(
        runners,
        "run_canonical_module",
        fail_after_paid_response,
    )

    with pytest.raises(StageExecutionError) as captured:
        runners.GenerateCandidateExpressionsRunner().run_instance(context)

    assert captured.value.category == "paid_response_persistence_failed"
    assert captured.value.retryable is False


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


def test_trace_program_state_builds_manifest_and_reruns_after_corruption(
    tmp_path,
    monkeypatch,
):
    calls = []

    def write_harness_output(arguments, context, payload):
        root = (
            Path(_argument_value(arguments, "--work-dir"))
            / "logs/run_evaluation"
            / _argument_value(arguments, "--run-id")
            / context.submission_id
            / context.instance.instance_id
        )
        for name in ("buggy_traces", "patched_traces"):
            directory = root / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "test.jsonl").write_text(
                f"{json.dumps(payload)}\n",
                encoding="utf-8",
            )

    def fake_command(module, arguments, context, **kwargs):
        arguments = tuple(arguments)
        calls.append((module, arguments, kwargs))
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
        if module == runners.TRACK_TEST_CALLS_MODULE:
            write_harness_output(
                arguments,
                context,
                {"target": "example:changed", "stack": []},
            )
            return
        if module == runners.SELECT_TRACE_FUNCTIONS_MODULE:
            Path(_argument_value(arguments, "--output-path")).write_text(
                json.dumps(
                    {
                        context.submission_id: {
                            context.instance.instance_id: ["example:called"]
                        }
                    }
                ),
                encoding="utf-8",
            )
            return

        if module == runners.BUILD_STEP1_MODULE:
            Path(_argument_value(arguments, "--output-path")).write_text(
                json.dumps(
                    {
                        context.submission_id: {
                            context.instance.instance_id: {
                                "file_path": "example.py",
                                "function_name": "example:changed",
                                "buggy_event_type": "Line",
                                "patched_event_type": "Line",
                                "buggy_statement": "return old",
                                "patched_statement": "return new",
                                "before_or_after": "before",
                                "buggy_lineno": 10,
                                "patched_lineno": 11,
                                "diff": {"values_changed": {}},
                                "buggy_variables": {},
                                "patched_variables": {},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            return

        if module == runners.BUILD_STEP2_MODULE:
            journal = PaidInferenceJournal(
                _argument_value(arguments, "--audit-dir"),
                prompt="candidate prompt",
                model_id=_argument_value(arguments, "--model"),
                reasoning_effort=_argument_value(
                    arguments,
                    "--reasoning-effort",
                ),
                response_schema=(
                    "dataset.extract_ground_truths.effect."
                    "infer_expression.ExpressionList"
                ),
            )
            source_response = journal.record_response(
                '{"expressions":[{"expr":"value"},{"expr":"other"}]}'
            )
            journal.select_response(source_response)
            Path(_argument_value(arguments, "--output-path")).write_text(
                json.dumps(
                    {
                        context.submission_id: {
                            context.instance.instance_id: {
                                "instance_id": context.instance.instance_id,
                                "agent": context.submission_id,
                                "file_path": "example.py",
                                "function_name": "example:changed",
                                "buggy_lineno": 10,
                                "patched_lineno": 11,
                                "buggy_line_count": 4,
                                "patched_line_count": 4,
                                "test_id": 0,
                                "before_or_after": "before",
                                "prompt_length_chars": 123,
                                "function_code_before_patch": (
                                    "def changed():\\n    return old"
                                ),
                                "buggy_function_param": {"value": 1},
                                "location": "before return old",
                                "changed_candidates": ["value"],
                                "unchanged_candidates": ["other"],
                                "_source_response": (
                                    journal.selected_response()
                                ),
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            return

        if module == runners.BUILD_STEP3_MODULE:
            if "--validate" in arguments:
                step2 = json.loads(
                    Path(
                        _argument_value(arguments, "--step2-path")
                    ).read_text(encoding="utf-8")
                )
                metadata = step2[context.submission_id][
                    context.instance.instance_id
                ]
                Path(_argument_value(arguments, "--output-path")).write_text(
                    json.dumps(
                        {
                            context.submission_id: {
                                context.instance.instance_id: {
                                    **metadata,
                                    "valid_changed_expressions": ["value"],
                                    "valid_unchanged_expressions": ["other"],
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                return
            inspection_root = (
                Path(_argument_value(arguments, "--inspection-work-dir"))
                / "logs"
                / "run_evaluation"
                / _argument_value(arguments, "--inspection-run-id-template")
                / context.submission_id
                / context.instance.instance_id
            )
            for name in ("buggy_traces", "patched_traces"):
                directory = inspection_root / name
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "test.jsonl").write_text(
                    '{"expr":["value","other"],"value":[1,2]}\n',
                    encoding="utf-8",
                )
            return

        if module == runners.BUILD_STEP4_MODULE:
            step3 = json.loads(
                Path(
                    _argument_value(arguments, "--step3-path")
                ).read_text(encoding="utf-8")
            )
            metadata = step3[context.submission_id][
                context.instance.instance_id
            ]
            Path(_argument_value(arguments, "--output-path")).write_text(
                json.dumps(
                    {
                        context.submission_id: {
                            context.instance.instance_id: {
                                "choices": [
                                    "value",
                                    "other",
                                    runners.NONE_OF_THE_ABOVE_CHOICE,
                                    runners.CANNOT_INFER_CHOICE,
                                ],
                                "answer": ["a"],
                                **{
                                    key: value
                                    for key, value in metadata.items()
                                    if key
                                    not in {
                                        "valid_changed_expressions",
                                        "valid_unchanged_expressions",
                                        "prompt_length_chars",
                                        "changed_candidates",
                                        "unchanged_candidates",
                                    }
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            return

        if module == runners.BUILD_STEP5_MODULE:
            step4 = json.loads(
                Path(
                    _argument_value(arguments, "--effect-step4-path")
                ).read_text(encoding="utf-8")
            )
            question = step4[context.submission_id][
                context.instance.instance_id
            ]
            filename = f"local_effect__{context.submission_id}.json"
            context_directory = Path(
                _argument_value(arguments, "--context-dir")
            )
            ground_truth_directory = Path(
                _argument_value(arguments, "--ground-truth-dir")
            )
            context_directory.mkdir(parents=True, exist_ok=True)
            ground_truth_directory.mkdir(parents=True, exist_ok=True)
            (context_directory / filename).write_text(
                json.dumps(
                    {
                        context.instance.instance_id: {
                            "function_code_before_patch": question[
                                "function_code_before_patch"
                            ],
                            "function_parameters_before_patch": "{'value': 1}\\n",
                            "line": question["location"],
                            "choices": question["choices"],
                            "before_or_after": question["before_or_after"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (ground_truth_directory / filename).write_text(
                json.dumps(
                    {
                        context.instance.instance_id: {
                            "answer": question["answer"]
                        }
                    }
                ),
                encoding="utf-8",
            )
            return

        assert module == runners.TRACE_PROGRAM_STATE_MODULE
        allowed_functions = json.loads(
            Path(
                _argument_value(arguments, "--allowed-functions-path")
            ).read_text(encoding="utf-8")
        )
        assert allowed_functions == {
            context.submission_id: {
                context.instance.instance_id: ["example:called"]
            }
        }
        write_harness_output(
            arguments,
            context,
            {"event": "line", "function": "example:called"},
        )

    monkeypatch.setattr(runners, "run_canonical_module", fake_command)
    config = LocalBuilderConfig(
        workspace=tmp_path / "workspace",
        artifact_output=tmp_path / "artifacts",
        max_workers=1,
        max_attempts=1,
        candidate_generation_model="candidate-model",
        candidate_generation_changed_candidates=4,
        candidate_generation_unchanged_candidates=5,
        candidate_generation_instance_workers=2,
        candidate_generation_agent_workers=3,
        candidate_generation_reasoning_effort="high",
        candidate_generation_model_retries=6,
        candidate_generation_command_timeout_seconds=765,
        candidate_generation_inference=True,
        expression_set_id=7,
        inspection_timeout_seconds=543,
        inspection_command_timeout_seconds=987,
        inspection_instance_workers=2,
        inspection_agent_workers=3,
        inspection_max_workers=0,
        inspection_force_rebuild=True,
        inspection_clean=True,
        choice_correct_count=1,
        choice_incorrect_count=1,
        choice_minimum_changed=1,
        choice_minimum_unchanged=1,
        choice_mmr_weight=0.6,
        choice_random_seed=17,
        choice_agent_workers=2,
        choice_command_timeout_seconds=246,
        export_parameter_max_characters=1234,
        export_command_timeout_seconds=135,
        trace_test_timeout_seconds=432,
        trace_command_timeout_seconds=876,
    )
    submission = make_submission()
    run_local_stage("identify-patched-functions", submission, config)
    run_local_stage("track-test-calls", submission, config, resume=True)
    run_local_stage("select-trace-functions", submission, config, resume=True)

    traced = run_local_stage(
        "trace-program-state",
        submission,
        config,
        resume=True,
    )
    resumed = run_local_stage(
        "trace-program-state",
        submission,
        config,
        resume=True,
    )

    assert traced.completed == 1
    assert resumed.reused == 1
    trace_calls = [
        item for item in calls if item[0] == runners.TRACE_PROGRAM_STATE_MODULE
    ]
    assert len(trace_calls) == 1
    trace_arguments = trace_calls[0][1]
    assert _argument_value(trace_arguments, "--max-workers") == "1"
    assert _argument_value(trace_arguments, "--timeout") == "432"
    assert trace_calls[0][2]["timeout"] == 876

    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    result = workspace.read_result("trace-program-state", INSTANCE_ID)
    manifest = result.data["artifact_manifest"]
    stage_instance = (
        config.workspace
        / "stages"
        / "trace-program-state"
        / "instances"
        / INSTANCE_ID
    )
    corrupt_path = (
        stage_instance / manifest["root"] / manifest["files"][0]["path"]
    )
    corrupt_path.write_text("corrupt\n", encoding="utf-8")

    rerun = run_local_stage(
        "trace-program-state",
        submission,
        config,
        resume=True,
    )

    assert rerun.completed == 1
    trace_calls = [
        item for item in calls if item[0] == runners.TRACE_PROGRAM_STATE_MODULE
    ]
    assert len(trace_calls) == 2
    assert workspace.read_status(
        "trace-program-state",
        INSTANCE_ID,
    ).total_attempts == 2

    divergence = run_local_stage(
        "find-first-divergence",
        submission,
        config,
        resume=True,
    )
    resumed_divergence = run_local_stage(
        "find-first-divergence",
        submission,
        config,
        resume=True,
    )

    assert divergence.completed == 1
    assert resumed_divergence.reused == 1
    divergence_calls = [
        item for item in calls if item[0] == runners.BUILD_STEP1_MODULE
    ]
    assert len(divergence_calls) == 1
    divergence_arguments = divergence_calls[0][1]
    assert _argument_value(divergence_arguments, "--agent") == "test-agent"
    assert _argument_value(divergence_arguments, "--instance-ids") == INSTANCE_ID
    assert _argument_value(divergence_arguments, "--depth-threshold") == "3"
    assert _argument_value(divergence_arguments, "--timeout") == "600"
    assert _argument_value(divergence_arguments, "--instance-workers") == "1"
    assert _argument_value(divergence_arguments, "--agent-workers") == "1"
    assert _argument_value(divergence_arguments, "--variable-max-depth") == "4"
    assert _argument_value(divergence_arguments, "--parameter-max-depth") == "3"
    assert "--simplify" in divergence_arguments
    assert divergence_calls[0][2]["timeout"] == 3600

    result = workspace.read_result("find-first-divergence", INSTANCE_ID)
    assert result.data["divergence"]["function_name"] == "example:changed"

    candidates = run_local_stage(
        "generate-candidate-expressions",
        submission,
        config,
        resume=True,
    )
    resumed_candidates = run_local_stage(
        "generate-candidate-expressions",
        submission,
        config,
        resume=True,
    )

    assert candidates.completed == 1
    assert resumed_candidates.reused == 1
    candidate_calls = [
        item for item in calls if item[0] == runners.BUILD_STEP2_MODULE
    ]
    assert len(candidate_calls) == 1
    candidate_arguments = candidate_calls[0][1]
    assert _argument_value(candidate_arguments, "--agent") == "test-agent"
    assert _argument_value(candidate_arguments, "--instance-ids") == INSTANCE_ID
    assert _argument_value(candidate_arguments, "--changed-candidates") == "4"
    assert _argument_value(candidate_arguments, "--unchanged-candidates") == "5"
    assert _argument_value(candidate_arguments, "--instance-workers") == "2"
    assert _argument_value(candidate_arguments, "--agent-workers") == "3"
    assert _argument_value(candidate_arguments, "--model") == "candidate-model"
    assert _argument_value(candidate_arguments, "--reasoning-effort") == "high"
    assert _argument_value(candidate_arguments, "--max-retries") == "6"
    assert _argument_value(candidate_arguments, "--audit-dir").endswith(
        "attempt-1/model-audit"
    )
    assert "--resume-audit-dir" not in candidate_arguments
    assert "--inference" in candidate_arguments
    assert candidate_calls[0][2]["timeout"] == 765

    result = workspace.read_result(
        "generate-candidate-expressions",
        INSTANCE_ID,
    )
    assert result.data["candidates"]["changed_candidates"] == ["value"]
    assert result.data["source_response"]["path"] == (
        "responses/response-0001.txt"
    )
    audit_paths = {
        item["path"] for item in result.data["artifact_manifest"]["files"]
    }
    assert audit_paths == {
        "manifest.json",
        "prompt.txt",
        "responses/response-0001.txt",
    }
    attempt = json.loads(
        (
            config.workspace
            / "stages/generate-candidate-expressions"
            / f"instances/{INSTANCE_ID}/work/attempt-1/attempt.json"
        ).read_text(encoding="utf-8")
    )
    assert attempt["artifact_manifests"] == ["model-audit/manifest.json"]

    executed = run_local_stage(
        "execute-candidate-expressions",
        submission,
        config,
        resume=True,
    )
    resumed_execution = run_local_stage(
        "execute-candidate-expressions",
        submission,
        config,
        resume=True,
    )

    assert executed.completed == 1
    assert resumed_execution.reused == 1
    execution_calls = [
        item for item in calls if item[0] == runners.BUILD_STEP3_MODULE
    ]
    assert len(execution_calls) == 1
    execution_arguments = execution_calls[0][1]
    assert "--execute" in execution_arguments
    assert "--no-process-gold" in execution_arguments
    assert _argument_value(execution_arguments, "--expression-set-id") == "7"
    assert _argument_value(execution_arguments, "--inspection-timeout") == "543"
    assert _argument_value(execution_arguments, "--instance-workers") == "2"
    assert _argument_value(execution_arguments, "--agent-workers") == "3"
    assert "--inspection-force-rebuild" in execution_arguments
    assert "--inspection-clean" in execution_arguments
    assert execution_calls[0][2]["timeout"] == 987

    result = workspace.read_result(
        "execute-candidate-expressions",
        INSTANCE_ID,
    )
    manifest = result.data["artifact_manifest"]
    manifest_paths = {item["path"] for item in manifest["files"]}
    assert manifest_paths == {
        "buggy_traces/test.jsonl",
        "patched_traces/test.jsonl",
    }
    execution_instance = (
        config.workspace
        / "stages"
        / "execute-candidate-expressions"
        / "instances"
        / INSTANCE_ID
    )
    corrupt_path = (
        execution_instance / manifest["root"] / manifest["files"][0]["path"]
    )
    corrupt_path.write_text("corrupt\n", encoding="utf-8")

    rerun_execution = run_local_stage(
        "execute-candidate-expressions",
        submission,
        config,
        resume=True,
    )

    assert rerun_execution.completed == 1
    execution_calls = [
        item for item in calls if item[0] == runners.BUILD_STEP3_MODULE
    ]
    assert len(execution_calls) == 2

    validated = run_local_stage(
        "validate-candidate-expressions",
        submission,
        config,
        resume=True,
    )
    resumed_validation = run_local_stage(
        "validate-candidate-expressions",
        submission,
        config,
        resume=True,
    )

    assert validated.completed == 1
    assert resumed_validation.reused == 1
    validation_calls = [
        item
        for item in calls
        if item[0] == runners.BUILD_STEP3_MODULE
        and "--validate" in item[1]
    ]
    assert len(validation_calls) == 1
    validation_arguments = validation_calls[0][1]
    assert "--execute" not in validation_arguments
    assert "--no-process-gold" in validation_arguments
    assert _argument_value(validation_arguments, "--expression-set-id") == "7"
    assert validation_calls[0][2]["timeout"] == 987
    result = workspace.read_result(
        "validate-candidate-expressions",
        INSTANCE_ID,
    )
    assert result.data["validated_candidates"][
        "valid_changed_expressions"
    ] == ["value"]

    choices = run_local_stage(
        "build-answer-choices",
        submission,
        config,
        resume=True,
    )
    resumed_choices = run_local_stage(
        "build-answer-choices",
        submission,
        config,
        resume=True,
    )

    assert choices.completed == 1
    assert resumed_choices.reused == 1
    choice_calls = [
        item for item in calls if item[0] == runners.BUILD_STEP4_MODULE
    ]
    assert len(choice_calls) == 1
    choice_arguments = choice_calls[0][1]
    assert _argument_value(choice_arguments, "--correct-choices") == "1"
    assert _argument_value(choice_arguments, "--incorrect-choices") == "1"
    assert _argument_value(choice_arguments, "--minimum-changed") == "1"
    assert _argument_value(choice_arguments, "--minimum-unchanged") == "1"
    assert _argument_value(choice_arguments, "--mmr-weight") == "0.6"
    assert _argument_value(choice_arguments, "--random-seed") == "17"
    assert _argument_value(choice_arguments, "--agent-workers") == "2"
    assert "--no-prepare-intent" in choice_arguments
    assert choice_calls[0][2]["timeout"] == 246
    result = workspace.read_result("build-answer-choices", INSTANCE_ID)
    assert result.data["question"]["answer"] == ["a"]
    assert result.data["correct_expressions"] == ["value"]

    exported = run_local_stage(
        "export-question-artifacts",
        submission,
        config,
        resume=True,
    )
    resumed_export = run_local_stage(
        "export-question-artifacts",
        submission,
        config,
        resume=True,
    )

    assert exported.completed == 1
    assert resumed_export.reused == 1
    export_calls = [
        item for item in calls if item[0] == runners.BUILD_STEP5_MODULE
    ]
    assert len(export_calls) == 1
    export_arguments = export_calls[0][1]
    assert _argument_value(export_arguments, "--kind") == "effect"
    assert _argument_value(export_arguments, "--agent") == "test-agent"
    assert _argument_value(
        export_arguments,
        "--parameter-max-characters",
    ) == "1234"
    assert export_calls[0][2]["timeout"] == 135
    context_path = (
        config.artifact_output
        / "context"
        / "local_effect__test-agent.json"
    )
    ground_truth_path = (
        config.artifact_output
        / "ground_truths"
        / "local_effect__test-agent.json"
    )
    assert config.artifact_output.is_symlink()
    assert json.loads(context_path.read_text(encoding="utf-8"))[
        INSTANCE_ID
    ]["line"] == "before return old"
    assert json.loads(ground_truth_path.read_text(encoding="utf-8"))[
        INSTANCE_ID
    ]["answer"] == ["a"]
    refreshed = LocalBuilderWorkspace.inspect(config.workspace)
    assert refreshed.manifest.artifact_output == str(config.artifact_output)
    assert refreshed.manifest.artifact_fingerprint


@pytest.mark.parametrize(
    ("candidate_data", "expected_reason"),
    [
        ({}, "no_candidate_expressions"),
        ({"prompt_length_chars": 123}, "candidate_inference_disabled"),
        (
            {
                "changed_candidates": [],
                "unchanged_candidates": [],
            },
            "no_candidate_expressions",
        ),
    ],
)
def test_expression_execution_skips_without_executable_candidates(
    tmp_path,
    candidate_data,
    expected_reason,
):
    context = replace(
        make_context(tmp_path),
        config=SimpleNamespace(
            choice_minimum_changed=1,
            choice_minimum_unchanged=3,
        ),
        upstream_results={
            "generate-candidate-expressions": StoredStageResult(
                outcome="completed",
                data={
                    "instance_id": INSTANCE_ID,
                    "candidates": candidate_data,
                    "inference": bool(candidate_data),
                },
            )
        },
    )

    result = runners.ExecuteCandidateExpressionsRunner().run_instance(context)

    assert result.outcome == "skipped"
    assert result.reason == expected_reason
    assert result.data["candidate_count"] == 0

    validation_context = replace(
        context,
        upstream_results={
            **context.upstream_results,
            "execute-candidate-expressions": result.to_stored(),
        },
    )
    validation = runners.ValidateCandidateExpressionsRunner().run_instance(
        validation_context
    )

    assert validation.outcome == "skipped"
    assert validation.reason == expected_reason

    choice_context = replace(
        validation_context,
        upstream_results={
            "validate-candidate-expressions": validation.to_stored(),
        },
    )
    choices = runners.BuildAnswerChoicesRunner().run_instance(choice_context)

    assert choices.outcome == "skipped"
    assert choices.reason == expected_reason


def test_answer_choices_skip_when_expression_pool_is_too_small(tmp_path):
    context = replace(
        make_context(tmp_path),
        config=SimpleNamespace(
            choice_minimum_changed=1,
            choice_minimum_unchanged=3,
        ),
        upstream_results={
            "validate-candidate-expressions": StoredStageResult(
                outcome="completed",
                data={
                    "instance_id": INSTANCE_ID,
                    "validated_candidates": {
                        "valid_changed_expressions": ["changed"],
                        "valid_unchanged_expressions": ["unchanged"],
                    },
                },
            )
        },
    )

    result = runners.BuildAnswerChoicesRunner().run_instance(context)

    assert result.outcome == "skipped"
    assert result.reason == "insufficient_expression_pool"
    assert result.data["changed_count"] == 1
    assert result.data["unchanged_count"] == 1
