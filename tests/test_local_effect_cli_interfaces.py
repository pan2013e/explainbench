import json
from pathlib import Path

import pytest

from dataset.extract_ground_truths.effect import build_step1
from dataset.extract_ground_truths.effect import build_step2
from dataset.extract_ground_truths.effect import build_step3
from dataset.extract_ground_truths.effect import build_step4
from dataset.extract_ground_truths.effect import build_step5
from dataset.extract_ground_truths.effect import (
    trace_step1_generate_qualname_whitelist as qualname_cli,
)
from dataset.extract_ground_truths.effect import (
    trace_step2_generate_call_stack_whitelist as call_stack_cli,
)
from execution import inspect as inspect_cli
from execution import trace as trace_cli
from execution import track as track_cli


INSTANCE_ID = "astropy__astropy-12907"
AGENT = "test-agent"


def test_qualname_cli_accepts_explicit_submission_paths(
    tmp_path,
    monkeypatch,
):
    predictions = tmp_path / "predictions.json"
    predictions.write_text(
        json.dumps({INSTANCE_ID: {"model_patch": "patch"}}),
        encoding="utf-8",
    )
    output = tmp_path / "allowed-qualnames.json"
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(qualname_cli, "get_instance_ids", lambda values: values)
    monkeypatch.setattr(
        qualname_cli,
        "load_swebench_dataset",
        lambda **kwargs: [
            {
                "instance_id": INSTANCE_ID,
                "repo": "astropy/astropy",
                "base_commit": "abc123",
            }
        ],
    )
    monkeypatch.setattr(
        qualname_cli,
        "ensure_repo_at_commit",
        lambda **kwargs: repository,
    )
    monkeypatch.setattr(
        qualname_cli,
        "extract_modified_qualnames",
        lambda **kwargs: [f"module:{kwargs['mode']}"],
    )
    monkeypatch.setattr(qualname_cli, "apply_patch_to_repo", lambda *args: None)

    qualname_cli.main(
        [
            "--agent",
            AGENT,
            "--predictions-path",
            str(predictions),
            "--instance-ids",
            INSTANCE_ID,
            "--repos-root",
            str(tmp_path / "repositories"),
            "--repository-remote",
            "https://example.invalid",
            "--output-path",
            str(output),
        ]
    )

    assert json.loads(output.read_text(encoding="utf-8")) == {
        AGENT: {INSTANCE_ID: ["module:new", "module:old"]}
    }


def test_call_stack_cli_accepts_explicit_tracking_and_output_paths(tmp_path):
    root = tmp_path / "track" / AGENT / INSTANCE_ID
    buggy = root / "buggy_traces"
    patched = root / "patched_traces"
    buggy.mkdir(parents=True)
    patched.mkdir(parents=True)
    trace_record = {
        "target": "module:changed",
        "stack": [["module", "caller"], ["module", "callee"]],
    }
    for directory in (buggy, patched):
        (directory / "test.jsonl").write_text(
            f"{json.dumps(trace_record)}\n",
            encoding="utf-8",
        )
    targets = tmp_path / "allowed-qualnames.json"
    targets.write_text(
        json.dumps({AGENT: {INSTANCE_ID: ["module:changed"]}}),
        encoding="utf-8",
    )
    output = tmp_path / "allowed-functions.json"

    call_stack_cli.main(
        [
            "--agent",
            AGENT,
            "--instance-ids",
            INSTANCE_ID,
            "--root-path",
            str(tmp_path / "track" / "{agent_name}" / "{instance_id}"),
            "--targets-json",
            str(targets),
            "--output-path",
            str(output),
        ]
    )

    assert json.loads(output.read_text(encoding="utf-8")) == {
        AGENT: {INSTANCE_ID: ["callee", "caller"]}
    }


@pytest.mark.parametrize(
    ("module", "runner_name", "whitelist_option", "whitelist_value"),
    [
        (
            track_cli,
            "run_tracking",
            "--allowed-qualnames-path",
            "qualnames.json",
        ),
        (
            trace_cli,
            "run_tracing",
            "--allowed-functions-path",
            "functions.json",
        ),
    ],
)
def test_execution_cli_dispatches_explicit_harness_options(
    monkeypatch,
    module,
    runner_name,
    whitelist_option,
    whitelist_value,
):
    captured = {}
    monkeypatch.setattr(module, runner_name, lambda **kwargs: captured.update(kwargs))

    module.main(
        [
            "--instance-ids",
            INSTANCE_ID,
            "--agent",
            AGENT,
            "--predictions-path",
            "predictions.json",
            whitelist_option,
            whitelist_value,
            "--run-id",
            "explicit-run",
            "--max-workers",
            "7",
            "--timeout",
            "123",
            "--clean",
        ]
    )

    assert captured["instance_ids"] == [INSTANCE_ID]
    assert captured["agent"] == AGENT
    assert captured["predictions_path"] == Path("predictions.json")
    assert captured["run_id"] == "explicit-run"
    assert captured["max_workers"] == 7
    assert captured["timeout"] == 123
    assert captured["clean"] is True


def test_tracking_runs_harness_in_explicit_work_directory(
    tmp_path,
    monkeypatch,
):
    captured = {}
    predictions = tmp_path / "predictions.json"
    predictions.write_text("{}\n", encoding="utf-8")
    qualnames = tmp_path / "qualnames.json"
    qualnames.write_text("{}\n", encoding="utf-8")
    work_dir = tmp_path / "tracking"
    report_dir = tmp_path / "reports"
    original_work_dir = Path.cwd()

    monkeypatch.setattr(track_cli, "monkey_patch_execution", lambda **kwargs: None)
    monkeypatch.setattr(track_cli, "prepare_tracer", lambda: None)
    monkeypatch.setattr(
        track_cli,
        "run_evaluation_main",
        lambda **kwargs: captured.update(
            {"cwd": Path.cwd(), "report_dir": kwargs["report_dir"]}
        ),
    )
    arguments = track_cli.build_parser().parse_args(
        [
            "--instance-ids",
            INSTANCE_ID,
            "--agent",
            AGENT,
            "--predictions-path",
            str(predictions),
            "--allowed-qualnames-path",
            str(qualnames),
            "--work-dir",
            str(work_dir),
            "--report-dir",
            str(report_dir),
        ]
    )

    track_cli.run_tracking(**vars(arguments))

    assert captured["cwd"] == work_dir.resolve()
    assert captured["report_dir"] == str(report_dir.resolve())
    assert Path.cwd() == original_work_dir


def test_inspection_cli_dispatches_predictions_run_id_and_timeout(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        inspect_cli,
        "inspect",
        lambda **kwargs: captured.update(kwargs),
    )

    inspect_cli.main(
        [
            "--instance-id",
            INSTANCE_ID,
            "--agent",
            AGENT,
            "--bp-file",
            "/testbed/example.py",
            "--pre-bp-line",
            "10",
            "--post-bp-line",
            "11",
            "--expr",
            "value",
            "--predictions-path",
            "predictions.json",
            "--run-id",
            "inspect-run",
            "--timeout",
            "456",
            "--max-workers",
            "2",
            "--force-rebuild",
            "--clean",
            "--report-dir",
            "reports",
        ]
    )

    assert captured["instance_id"] == INSTANCE_ID
    assert captured["predictions_path"] == Path("predictions.json")
    assert captured["run_id"] == "inspect-run"
    assert captured["timeout"] == 456
    assert captured["max_workers"] == 2
    assert captured["force_rebuild"] is True
    assert captured["clean"] is True
    assert captured["report_dir"] == Path("reports")


def test_build_step_parsers_expose_a_consistent_single_agent_contract():
    step1 = build_step1.build_parser().parse_args(
        ["--agent", AGENT, "--instance-ids", INSTANCE_ID]
    )
    step2 = build_step2.build_parser().parse_args(
        [
            "--agent",
            AGENT,
            "--instance-ids",
            INSTANCE_ID,
            "--predictions-path",
            "predictions.json",
            "--model",
            "candidate-model",
        ]
    )
    step3 = build_step3.build_parser().parse_args(
        [
            "--execute",
            "--agent",
            AGENT,
            "--instance-ids",
            INSTANCE_ID,
            "--inspection-run-id-template",
            "inspect.{agent}.{expr_id}",
            "--inspection-timeout",
            "789",
            "--inspection-clean",
        ]
    )
    step4 = build_step4.build_parser().parse_args(
        ["--agent", AGENT, "--instance-ids", INSTANCE_ID]
    )
    step5 = build_step5.build_parser().parse_args(
        ["--kind", "effect", "--agent", AGENT, "--instance-ids", INSTANCE_ID]
    )

    for parsed in (step1, step2, step3, step4, step5):
        assert parsed.agent == [AGENT]
        assert parsed.instance_ids == [INSTANCE_ID]
    assert step2.predictions_path == "predictions.json"
    assert step2.model == "candidate-model"
    assert step3.inspection_run_id_template == "inspect.{agent}.{expr_id}"
    assert step3.inspection_timeout == 789
    assert step3.inspection_clean is True


def test_build_step3_requires_exactly_one_operation():
    parser = build_step3.build_parser()

    with pytest.raises(SystemExit, match="2"):
        parser.parse_args(["--agent", AGENT])
    with pytest.raises(SystemExit, match="2"):
        parser.parse_args(["--execute", "--validate", "--agent", AGENT])


def test_build_step5_exports_only_selected_effect_instances(tmp_path):
    step4 = tmp_path / "step4.json"
    step4.write_text(
        json.dumps(
            {
                AGENT: {
                    INSTANCE_ID: {
                        "function_code_before_patch": "def example(): pass",
                        "buggy_function_param": {"value": "x"},
                        "location": "return value",
                        "choices": ["value", "other"],
                        "before_or_after": "after",
                        "answer": ["a"],
                    },
                    "other__project-1": {
                        "function_code_before_patch": "def other(): pass",
                        "buggy_function_param": {},
                        "location": "return other",
                        "choices": ["other"],
                        "before_or_after": "after",
                        "answer": ["a"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    context_dir = tmp_path / "context"
    ground_truth_dir = tmp_path / "ground_truths"

    build_step5.main(
        [
            "--kind",
            "effect",
            "--agent",
            AGENT,
            "--instance-ids",
            INSTANCE_ID,
            "--effect-step4-path",
            str(step4),
            "--context-dir",
            str(context_dir),
            "--ground-truth-dir",
            str(ground_truth_dir),
        ]
    )

    context = json.loads(
        (context_dir / f"local_effect__{AGENT}.json").read_text(
            encoding="utf-8"
        )
    )
    ground_truth = json.loads(
        (ground_truth_dir / f"local_effect__{AGENT}.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(context) == {INSTANCE_ID}
    assert ground_truth == {INSTANCE_ID: {"answer": ["a"]}}


def test_canonical_modules_do_not_import_package_stage_implementations():
    roots = [Path("dataset/extract_ground_truths/effect"), Path("execution")]
    offenders = []
    for root in roots:
        for path in root.rglob("*.py"):
            if "explainbench.question_builders" in path.read_text(encoding="utf-8"):
                offenders.append(str(path))

    assert offenders == []
