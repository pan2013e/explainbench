import pytest

from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.question_builders.local.stages.find_first_divergence import (
    FindFirstDivergenceRunner,
    path_depth,
    simplify_value,
)
from explainbench.schemas import SubmissionInstance


class Config:
    divergence_depth = 3
    variable_max_depth = 1
    parameter_max_depth = 1
    random_seed = 42


def make_context(tmp_path, finder_data, *, existing=True):
    buggy = tmp_path / "buggy.jsonl"
    patched = tmp_path / "patched.jsonl"
    if existing:
        buggy.write_text("{}\n", encoding="utf-8")
        patched.write_text("{}\n", encoding="utf-8")
    return StageContext(
        instance=SubmissionInstance(
            instance_id="owner__project-1",
            explanation="Explanation",
            model_patch="patch",
        ),
        workspace=tmp_path,
        work_directory=tmp_path / "work",
        log_directory=tmp_path / "logs",
        upstream_results={
            "trace-program-state": StoredStageResult(
                outcome="completed",
                data={
                    "trace_pairs": [
                        {
                            "test_id": 0,
                            "buggy_trace_file": buggy.name,
                            "patched_trace_file": patched.name,
                            "removed_lines": {"example.py": [1]},
                            "added_lines": {"example.py": [1]},
                        }
                    ]
                },
            )
        },
        config=Config(),
        submission_id="test-agent",
    )


def test_divergence_runner_simplifies_and_records_agent_metadata(tmp_path):
    received = {}

    def finder(**kwargs):
        received.update(kwargs)
        return {
            "buggy_variables": {"value": {"nested": {"too_deep": 1}}},
            "patched_variables": {"value": {"nested": {"too_deep": 2}}},
            "buggy_function_param": {"value": {"nested": {"too_deep": 1}}},
            "location": "return value",
        }

    runner = FindFirstDivergenceRunner(finder)
    result = runner.run_instance(make_context(tmp_path, finder)).to_stored()
    runner.validate_result(result)

    assert result.data["outcome"] == "agent_divergence"
    assert received["submission_id"] == "test-agent"
    assert result.data["metadata"]["buggy_variables"]["value"]["nested"] == {
        "py/object": "builtins.dict"
    }


def test_no_divergence_in_valid_trace_is_explicit_gold_fallback(tmp_path):
    runner = FindFirstDivergenceRunner(lambda **kwargs: {})

    result = runner.run_instance(make_context(tmp_path, {})).to_stored()

    assert result.data == {
        "outcome": "gold_fallback",
        "metadata": None,
        "fallback_reason": "no_usable_agent_divergence",
    }


def test_missing_trace_is_failure_not_gold_fallback(tmp_path):
    runner = FindFirstDivergenceRunner(lambda **kwargs: {})

    with pytest.raises(StageExecutionError) as captured:
        runner.run_instance(make_context(tmp_path, {}, existing=False))

    assert captured.value.category == "detailed_traces_unusable"
    assert captured.value.retryable is True


def test_path_depth_and_simplification_match_legacy_shapes():
    assert path_depth("root['seen_variables']['value']['field']") == 2
    assert path_depth("root['other']['value']") == 2
    assert simplify_value([[[1]]], max_depth=1) == [
        [{"py/object": "builtins.list", "len": 1}]
    ]

