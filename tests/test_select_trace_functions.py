import json

import pytest

from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.question_builders.local.stages.select_trace_functions import (
    SelectTraceFunctionsRunner,
    collect_trace_functions,
)
from explainbench.schemas import SubmissionInstance


TARGET = "package.module:Example.method"


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )


def test_collect_trace_functions_filters_targets_and_malformed_frames(tmp_path):
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    write_jsonl(
        first,
        [
            {
                "target": TARGET,
                "stack": [
                    ["package.module", "caller"],
                    ["package.module", "callee", 12],
                    ["incomplete"],
                ],
            },
            {"target": "unrelated", "stack": [["other", "ignored"]]},
        ],
    )
    write_jsonl(
        second,
        [{"target": TARGET, "stack": [["package.module", "caller"]]}],
    )

    assert collect_trace_functions([first, second], [TARGET]) == [
        "callee",
        "caller",
    ]


def test_select_trace_functions_combines_buggy_and_patched_files(tmp_path):
    buggy = tmp_path / "track" / "buggy_traces" / "test.jsonl"
    patched = tmp_path / "track" / "patched_traces" / "test.jsonl"
    write_jsonl(buggy, [{"target": TARGET, "stack": [["m", "buggy_caller"]]}])
    write_jsonl(
        patched,
        [{"target": TARGET, "stack": [["m", "patched_caller"]]}],
    )
    runner = SelectTraceFunctionsRunner()
    context = StageContext(
        instance=SubmissionInstance(
            instance_id="owner__project-1",
            explanation="Explanation",
            model_patch="patch",
        ),
        workspace=tmp_path,
        work_directory=tmp_path / "work",
        log_directory=tmp_path / "logs",
        upstream_results={
            "identify-patched-functions": StoredStageResult(
                outcome="completed",
                data={
                    "repository": "owner/project",
                    "base_commit": "abc123",
                    "old_functions": [TARGET],
                    "new_functions": [TARGET],
                    "patched_functions": [TARGET],
                },
            ),
            "track-test-calls": StoredStageResult(
                outcome="completed",
                data={
                    "buggy_trace_files": [str(buggy.relative_to(tmp_path))],
                    "patched_trace_files": [str(patched.relative_to(tmp_path))],
                },
            ),
        },
        config=object(),
    )

    result = runner.run_instance(context).to_stored()
    runner.validate_result(result)

    assert result.data["trace_functions"] == [
        "buggy_caller",
        "patched_caller",
    ]


def test_select_trace_functions_reports_missing_tracking_file(tmp_path):
    runner = SelectTraceFunctionsRunner()
    upstream = {
        "identify-patched-functions": StoredStageResult(
            outcome="completed",
            data={
                "repository": "owner/project",
                "base_commit": "abc123",
                "old_functions": [TARGET],
                "new_functions": [TARGET],
                "patched_functions": [TARGET],
            },
        ),
        "track-test-calls": StoredStageResult(
            outcome="completed",
            data={
                "buggy_trace_files": ["missing-buggy.jsonl"],
                "patched_trace_files": ["missing-patched.jsonl"],
            },
        ),
    }
    context = StageContext(
        instance=SubmissionInstance(
            instance_id="owner__project-1",
            explanation="Explanation",
            model_patch="patch",
        ),
        workspace=tmp_path,
        work_directory=tmp_path / "work",
        log_directory=tmp_path / "logs",
        upstream_results=upstream,
        config=object(),
    )

    with pytest.raises(StageExecutionError) as captured:
        runner.run_instance(context)

    assert captured.value.category == "tracked_calls_invalid"
    assert captured.value.retryable is True

