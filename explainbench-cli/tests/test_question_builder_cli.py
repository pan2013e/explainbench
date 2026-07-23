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
        if module in {
            runners.TRACK_TEST_CALLS_MODULE,
            runners.TRACE_PROGRAM_STATE_MODULE,
        }:
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
        if module == runners.BUILD_STEP1_MODULE:
            Path(option(arguments, "--output-path")).write_text(
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
                                "diff": {},
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
            Path(option(arguments, "--output-path")).write_text(
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
                                "unchanged_candidates": [
                                    "other_1",
                                    "other_2",
                                    "other_3",
                                ],
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
                    Path(option(arguments, "--step2-path")).read_text(
                        encoding="utf-8"
                    )
                )
                metadata = step2[context.submission_id][
                    context.instance.instance_id
                ]
                Path(option(arguments, "--output-path")).write_text(
                    json.dumps(
                        {
                            context.submission_id: {
                                context.instance.instance_id: {
                                    **metadata,
                                    "valid_changed_expressions": ["value"],
                                    "valid_unchanged_expressions": [
                                        "other_1",
                                        "other_2",
                                        "other_3",
                                    ],
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                return
            inspection_root = (
                Path(option(arguments, "--inspection-work-dir"))
                / "logs"
                / "run_evaluation"
                / option(arguments, "--inspection-run-id-template")
                / context.submission_id
                / context.instance.instance_id
            )
            for name in ("buggy_traces", "patched_traces"):
                directory = inspection_root / name
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "test.jsonl").write_text(
                    "{}\n",
                    encoding="utf-8",
                )
            return
        if module == runners.BUILD_STEP4_MODULE:
            step3 = json.loads(
                Path(option(arguments, "--step3-path")).read_text(
                    encoding="utf-8"
                )
            )
            metadata = step3[context.submission_id][
                context.instance.instance_id
            ]
            Path(option(arguments, "--output-path")).write_text(
                json.dumps(
                    {
                        context.submission_id: {
                            context.instance.instance_id: {
                                "choices": [
                                    "value",
                                    "other_1",
                                    "other_2",
                                    "other_3",
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
                Path(option(arguments, "--effect-step4-path")).read_text(
                    encoding="utf-8"
                )
            )
            question = step4[context.submission_id][
                context.instance.instance_id
            ]
            filename = f"local_effect__{context.submission_id}.json"
            context_directory = Path(option(arguments, "--context-dir"))
            ground_truth_directory = Path(
                option(arguments, "--ground-truth-dir")
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
        if module == runners.SELECT_TRACE_FUNCTIONS_MODULE:
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
            return
        raise AssertionError(f"unexpected canonical module: {module}")

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


def test_complete_pipeline_publishes_artifacts_and_status_is_inspectable(
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

    assert status == 0
    assert run_output.err == ""
    assert "Local question building complete" in run_output.out
    assert "identify-patched-functions" in run_output.out
    assert (workspace / "manifest.json").is_file()
    assert artifacts.is_symlink()
    assert (
        artifacts / "context" / "local_effect__test-agent.json"
    ).is_file()
    assert (
        artifacts / "ground_truths" / "local_effect__test-agent.json"
    ).is_file()

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
    assert "build-answer-choices: completed=1" in status_output.out
    assert "export-question-artifacts: completed=1" in status_output.out
    assert f"Artifacts: {artifacts}" in status_output.out


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
trace_test_timeout_seconds = 345
trace_command_timeout_seconds = 890
divergence_depth_threshold = 2
divergence_timeout_seconds = 111
divergence_command_timeout_seconds = 222
divergence_instance_workers = 1
divergence_agent_workers = 1
divergence_simplify = false
divergence_variable_max_depth = 5
divergence_parameter_max_depth = 4
candidate_generation_changed_candidates = 4
candidate_generation_unchanged_candidates = 5
candidate_generation_inference = false
candidate_generation_instance_workers = 2
candidate_generation_agent_workers = 3
candidate_generation_reasoning_effort = "high"
candidate_generation_model_retries = 6
candidate_generation_command_timeout_seconds = 765
expression_set_id = 7
inspection_timeout_seconds = 543
inspection_command_timeout_seconds = 987
inspection_instance_workers = 2
inspection_agent_workers = 3
inspection_max_workers = 0
inspection_force_rebuild = true
inspection_cache_level = "env"
inspection_clean = true
inspection_open_file_limit = 4096
inspection_rewrite_reports = false
inspection_modal = false
inspection_instance_image_tag = "latest"
inspection_env_image_tag = "latest"
inspection_split = "test"
inspection_namespace = "swebench"
choice_correct_count = 1
choice_incorrect_count = 3
choice_minimum_changed = 1
choice_minimum_unchanged = 3
choice_mmr_weight = 0.7
choice_random_seed = 42
choice_agent_workers = 2
choice_command_timeout_seconds = 321
export_parameter_max_characters = 1234
export_command_timeout_seconds = 432

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
    assert status == 0
    assert (tmp_path / "configured-workspace" / "manifest.json").is_file()
    assert (tmp_path / "configured-workspace" / "input/predictions.json").is_file()
    assert (tmp_path / "configured-artifacts").is_symlink()


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
