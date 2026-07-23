import json

import pytest

from explainbench.question_builders.common.locking import (
    WorkspaceLock,
    WorkspaceLockedError,
)
from explainbench.question_builders.common.orchestration import (
    MissingPrerequisiteError,
    StageDefinition,
    StageExecutionError,
    StageRegistry,
    StageResult,
)
from explainbench.question_builders.local.config import LocalBuilderConfig
from explainbench.question_builders.local.service import (
    run_local_pipeline,
    run_local_stage,
)
from explainbench.question_builders.local.workspace import LocalBuilderWorkspace
from explainbench.schemas import Submission


PATCH = """\
diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old
+new
"""


class RecordingRunner:
    def __init__(self, *, interrupt_on=None):
        self.calls = []
        self.interrupt_on = interrupt_on

    def run_instance(self, context):
        self.calls.append(context.instance.instance_id)
        if context.instance.instance_id == self.interrupt_on:
            raise KeyboardInterrupt
        return StageResult.completed(
            {
                "instance_id": context.instance.instance_id,
                "upstream": sorted(context.upstream_results),
            }
        )

    def validate_result(self, result):
        if "instance_id" not in result.data:
            raise ValueError("missing instance_id")


class FlakyRunner(RecordingRunner):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    def run_instance(self, context):
        self.attempts += 1
        if self.attempts == 1:
            raise StageExecutionError(
                "temporary failure",
                category="temporary_test_failure",
                retryable=True,
            )
        return super().run_instance(context)


class FailingRunner(RecordingRunner):
    def __init__(self, *, retryable):
        super().__init__()
        self.retryable = retryable

    def run_instance(self, context):
        self.calls.append(context.instance.instance_id)
        raise StageExecutionError(
            "stage failure",
            category="test_failure",
            retryable=self.retryable,
        )


class SkippingRunner(RecordingRunner):
    def run_instance(self, context):
        self.calls.append(context.instance.instance_id)
        return StageResult.skipped(
            "not_applicable",
            {"instance_id": context.instance.instance_id},
        )


def make_submission(instance_count=2):
    return Submission.model_validate(
        {
            "submission_id": "test-agent",
            "instances": [
                {
                    "instance_id": f"repo__project-{index}",
                    "explanation": "Explanation",
                    "model_patch": PATCH,
                }
                for index in range(instance_count)
            ],
        }
    )


def make_config(tmp_path, *, model="candidate-model", max_attempts=3):
    return LocalBuilderConfig(
        workspace=tmp_path / "workspace",
        artifact_output=tmp_path / "artifacts",
        max_workers=1,
        max_attempts=max_attempts,
        candidate_generation_model=model,
    )


def make_definition(
    name,
    runner,
    *,
    dependencies=(),
    semantic_inputs=None,
    accepts_skipped_dependencies=False,
):
    keywords = {}
    if semantic_inputs is not None:
        keywords["semantic_inputs"] = semantic_inputs
    return StageDefinition(
        name=name,
        description=f"Run {name}",
        dependencies=dependencies,
        implementation_version="test-v1",
        runner=runner,
        accepts_skipped_dependencies=accepts_skipped_dependencies,
        **keywords,
    )


def test_stage_can_explicitly_accept_skipped_dependencies(tmp_path):
    first = SkippingRunner()
    strict = RecordingRunner()
    accepting = RecordingRunner()
    registry = StageRegistry(
        [
            make_definition("first", first),
            make_definition("strict", strict, dependencies=("first",)),
            make_definition(
                "accepting",
                accepting,
                dependencies=("first",),
                accepts_skipped_dependencies=True,
            ),
        ]
    )

    summaries = run_local_pipeline(
        make_submission(instance_count=1),
        make_config(tmp_path),
        registry=registry,
    )

    assert summaries[0].skipped == 1
    assert summaries[1].blocked == 1
    assert summaries[2].completed == 1
    assert strict.calls == []
    assert accepting.calls == ["repo__project-0"]


def test_pipeline_runs_dependencies_then_reuses_completed_results(tmp_path):
    first = RecordingRunner()
    second = RecordingRunner()
    registry = StageRegistry(
        [
            make_definition("first", first),
            make_definition("second", second, dependencies=("first",)),
        ]
    )
    submission = make_submission()
    config = make_config(tmp_path)

    initial = run_local_pipeline(submission, config, registry=registry)
    resumed = run_local_pipeline(
        submission,
        config,
        registry=registry,
        resume=True,
    )

    assert [summary.stage for summary in initial] == ["first", "second"]
    assert [summary.completed for summary in initial] == [2, 2]
    assert [summary.reused for summary in resumed] == [2, 2]
    assert first.calls == ["repo__project-0", "repo__project-1"]
    assert second.calls == ["repo__project-0", "repo__project-1"]


def test_interrupted_instance_is_resumed_without_rerunning_completed_one(tmp_path):
    interrupting = RecordingRunner(interrupt_on="repo__project-1")
    registry = StageRegistry([make_definition("work", interrupting)])
    submission = make_submission()
    config = make_config(tmp_path)

    with pytest.raises(KeyboardInterrupt):
        run_local_pipeline(submission, config, registry=registry)

    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    assert workspace.read_status("work", "repo__project-0").state == "completed"
    assert workspace.read_status("work", "repo__project-1").state == "running"

    finishing = RecordingRunner()
    resumed_registry = StageRegistry([make_definition("work", finishing)])
    summaries = run_local_pipeline(
        submission,
        config,
        registry=resumed_registry,
        resume=True,
    )

    assert summaries[0].reused == 1
    assert summaries[0].completed == 1
    assert finishing.calls == ["repo__project-1"]
    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    status = workspace.read_status("work", "repo__project-1")
    assert status.retry_cycle == 2
    assert status.cycle_attempt == 1
    assert status.total_attempts == 2
    first_attempt = json.loads(
        (
            config.workspace
            / "stages/work/instances/repo__project-1/work/attempt-1/attempt.json"
        ).read_text(encoding="utf-8")
    )
    second_attempt = json.loads(
        (
            config.workspace
            / "stages/work/instances/repo__project-1/work/attempt-2/attempt.json"
        ).read_text(encoding="utf-8")
    )
    assert first_attempt["state"] == "interrupted"
    assert second_attempt["state"] == "completed"


def test_retryable_failure_is_checkpointed_and_retried(tmp_path):
    runner = FlakyRunner()
    registry = StageRegistry([make_definition("flaky", runner)])
    submission = make_submission(instance_count=1)
    config = make_config(tmp_path, max_attempts=2)

    summary = run_local_pipeline(submission, config, registry=registry)[0]

    assert summary.completed == 1
    assert runner.attempts == 2
    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    status = workspace.read_status("flaky", "repo__project-0")
    assert status.state == "completed"
    assert status.retry_cycle == 1
    assert status.cycle_attempt == 2
    assert status.total_attempts == 2


def test_resume_starts_fresh_cycle_after_retry_budget_is_exhausted(tmp_path):
    failing = FailingRunner(retryable=True)
    registry = StageRegistry([make_definition("work", failing)])
    submission = make_submission(instance_count=1)
    config = make_config(tmp_path, max_attempts=2)

    first = run_local_pipeline(submission, config, registry=registry)[0]

    assert first.failed == 1
    assert len(failing.calls) == 2
    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    status = workspace.read_status("work", "repo__project-0")
    assert status.retry_cycle == 1
    assert status.cycle_attempt == 2
    assert status.total_attempts == 2

    finishing = RecordingRunner()
    resumed_registry = StageRegistry([make_definition("work", finishing)])
    resumed = run_local_pipeline(
        submission,
        config,
        registry=resumed_registry,
        resume=True,
    )[0]

    assert resumed.completed == 1
    assert finishing.calls == ["repo__project-0"]
    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    status = workspace.read_status("work", "repo__project-0")
    assert status.retry_cycle == 2
    assert status.cycle_attempt == 1
    assert status.total_attempts == 3
    attempts = [
        json.loads(path.read_text(encoding="utf-8"))["state"]
        for path in sorted(
            (
                config.workspace
                / "stages/work/instances/repo__project-0/work"
            ).glob("attempt-*/attempt.json")
        )
    ]
    assert attempts == ["failed", "failed", "completed"]


def test_resume_preserves_non_retryable_failure(tmp_path):
    failing = FailingRunner(retryable=False)
    registry = StageRegistry([make_definition("work", failing)])
    submission = make_submission(instance_count=1)
    config = make_config(tmp_path, max_attempts=3)

    first = run_local_pipeline(submission, config, registry=registry)[0]
    resumed = run_local_pipeline(
        submission,
        config,
        registry=registry,
        resume=True,
    )[0]

    assert first.failed == 1
    assert resumed.failed == 1
    assert failing.calls == ["repo__project-0"]
    workspace = LocalBuilderWorkspace.inspect(config.workspace)
    status = workspace.read_status("work", "repo__project-0")
    assert status.retry_cycle == 1
    assert status.cycle_attempt == 1
    assert status.total_attempts == 1


def test_resume_migrates_version_one_status_without_rerunning(tmp_path):
    runner = RecordingRunner()
    registry = StageRegistry([make_definition("work", runner)])
    submission = make_submission(instance_count=1)
    config = make_config(tmp_path)
    run_local_pipeline(submission, config, registry=registry)
    status_path = (
        config.workspace
        / "stages/work/instances/repo__project-0/status.json"
    )
    current = json.loads(status_path.read_text(encoding="utf-8"))
    version_one = {
        key: value
        for key, value in current.items()
        if key
        not in {
            "schema_version",
            "semantic_fingerprint",
            "execution_fingerprint",
            "retry_cycle",
            "cycle_attempt",
            "total_attempts",
        }
    }
    version_one.update(
        {
            "schema_version": 1,
            "fingerprint": current["semantic_fingerprint"],
            "attempts": current["total_attempts"],
        }
    )
    status_path.write_text(
        f"{json.dumps(version_one, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )

    inspected = LocalBuilderWorkspace.inspect(config.workspace)
    assert inspected.read_status("work", "repo__project-0").schema_version == 2
    assert json.loads(status_path.read_text(encoding="utf-8"))["schema_version"] == 1

    summary = run_local_pipeline(
        submission,
        config,
        registry=registry,
        resume=True,
    )[0]

    assert summary.reused == 1
    assert runner.calls == ["repo__project-0"]
    migrated = json.loads(status_path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 2
    assert migrated["retry_cycle"] == 1
    assert migrated["cycle_attempt"] == 1
    assert migrated["total_attempts"] == 1


def test_corrupt_result_reruns_affected_stage_and_downstream(tmp_path):
    first = RecordingRunner()
    second = RecordingRunner()
    registry = StageRegistry(
        [
            make_definition("first", first),
            make_definition("second", second, dependencies=("first",)),
        ]
    )
    submission = make_submission(instance_count=1)
    config = make_config(tmp_path)
    run_local_pipeline(submission, config, registry=registry)
    result_path = (
        config.workspace
        / "stages"
        / "first"
        / "instances"
        / "repo__project-0"
        / "result.json"
    )
    result_path.write_text("not JSON", encoding="utf-8")

    summaries = run_local_pipeline(
        submission,
        config,
        registry=registry,
        resume=True,
    )

    assert [summary.completed for summary in summaries] == [1, 1]
    assert first.calls == ["repo__project-0", "repo__project-0"]
    assert second.calls == ["repo__project-0", "repo__project-0"]
    assert json.loads(result_path.read_text(encoding="utf-8"))["outcome"] == (
        "completed"
    )


def test_semantic_change_invalidates_only_affected_stage_and_downstream(tmp_path):
    first = RecordingRunner()
    second = RecordingRunner()
    registry = StageRegistry(
        [
            make_definition("first", first),
            make_definition(
                "second",
                second,
                dependencies=("first",),
                semantic_inputs=lambda config: {
                    "model": config.candidate_generation_model
                },
            ),
        ]
    )
    submission = make_submission(instance_count=1)
    run_local_pipeline(submission, make_config(tmp_path), registry=registry)

    summaries = run_local_pipeline(
        submission,
        make_config(tmp_path, model="different-model"),
        registry=registry,
        resume=True,
    )

    assert summaries[0].reused == 1
    assert summaries[1].completed == 1
    assert first.calls == ["repo__project-0"]
    assert second.calls == ["repo__project-0", "repo__project-0"]
    workspace = LocalBuilderWorkspace.inspect(make_config(tmp_path).workspace)
    status = workspace.read_status("second", "repo__project-0")
    assert status.retry_cycle == 2
    assert status.cycle_attempt == 1
    assert status.total_attempts == 2


def test_operational_changes_do_not_invalidate_results(tmp_path):
    runner = RecordingRunner()
    registry = StageRegistry([make_definition("work", runner)])
    submission = make_submission(instance_count=1)
    config = make_config(tmp_path, max_attempts=1)
    run_local_pipeline(submission, config, registry=registry)
    changed = LocalBuilderConfig(
        workspace=config.workspace,
        artifact_output=config.artifact_output,
        max_workers=8,
        max_attempts=9,
        candidate_generation_model=config.candidate_generation_model,
    )

    summary = run_local_pipeline(
        submission,
        changed,
        registry=registry,
        resume=True,
    )[0]

    assert summary.reused == 1
    assert runner.calls == ["repo__project-0"]


def test_individual_stage_requires_compatible_prerequisites(tmp_path):
    registry = StageRegistry(
        [
            make_definition("first", RecordingRunner()),
            make_definition(
                "second",
                RecordingRunner(),
                dependencies=("first",),
            ),
        ]
    )

    with pytest.raises(MissingPrerequisiteError, match="Run the missing"):
        run_local_stage(
            "second",
            make_submission(instance_count=1),
            make_config(tmp_path),
            registry=registry,
        )


def test_second_workspace_writer_is_rejected(tmp_path):
    workspace = tmp_path / "workspace"

    with WorkspaceLock(workspace):
        with pytest.raises(WorkspaceLockedError, match="already in use"):
            WorkspaceLock(workspace).acquire()


def test_registry_rejects_cycles():
    runner = RecordingRunner()

    with pytest.raises(ValueError, match="cycle"):
        StageRegistry(
            [
                make_definition("first", runner, dependencies=("second",)),
                make_definition("second", runner, dependencies=("first",)),
            ]
        )
