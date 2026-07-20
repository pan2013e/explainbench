from explainbench.evaluation.artifacts import load_task_artifacts
from explainbench.evaluation.registry import TaskName
from explainbench.question_builders.common.orchestration import (
    StageDefinition,
    StageRegistry,
    StageResult,
)
from explainbench.question_builders.local.config import LocalBuilderConfig
from explainbench.question_builders.local.service import run_local_pipeline
from explainbench.question_builders.local.stages.build_answer_choices import (
    BuildAnswerChoicesRunner,
)
from explainbench.question_builders.local.stages.export_question_artifacts import (
    ExportQuestionArtifactsRunner,
    format_function_parameters,
)
from explainbench.question_builders.local.stages.validate_candidate_expressions import (
    ValidateCandidateExpressionsRunner,
)
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


class ExecutedExpressionsRunner:
    def run_instance(self, context):
        return StageResult.completed(
            {
                "metadata": {
                    "function_code_before_patch": (
                        "def example(value):\n    return value"
                    ),
                    "buggy_function_param": {"value": 1},
                    "location": "return value",
                    "before_or_after": "before",
                },
                "candidates": ["value", "value + 1", "value - 1", "str(value)"],
                "buggy_inspection": {
                    "expr": ["value", "value + 1", "value - 1", "str(value)"],
                    "value": [1, 2, 0, "1"],
                    "exception": [None, None, None, None],
                },
                "patched_inspection": {
                    "expr": ["value", "value + 1", "value - 1", "str(value)"],
                    "value": [2, 2, 0, "1"],
                    "exception": [None, None, None, None],
                },
            }
        )

    def validate_result(self, result):
        assert result.data["candidates"]


def test_export_pipeline_publishes_evaluator_compatible_artifacts(tmp_path):
    registry = StageRegistry(
        [
            StageDefinition(
                name="execute-candidate-expressions",
                description="fixture execution",
                dependencies=(),
                implementation_version="fixture-1",
                runner=ExecutedExpressionsRunner(),
            ),
            StageDefinition(
                name="validate-candidate-expressions",
                description="validate",
                dependencies=("execute-candidate-expressions",),
                implementation_version="1",
                runner=ValidateCandidateExpressionsRunner(),
            ),
            StageDefinition(
                name="build-answer-choices",
                description="choices",
                dependencies=("validate-candidate-expressions",),
                implementation_version="1",
                runner=BuildAnswerChoicesRunner(),
            ),
            StageDefinition(
                name="export-question-artifacts",
                description="export",
                dependencies=("build-answer-choices",),
                implementation_version="1",
                runner=ExportQuestionArtifactsRunner(),
            ),
        ]
    )
    submission = Submission.model_validate(
        {
            "submission_id": "test-agent",
            "instances": [
                {
                    "instance_id": INSTANCE_ID,
                    "explanation": "Explanation",
                    "model_patch": PATCH,
                }
            ],
        }
    )
    config = LocalBuilderConfig(
        workspace=tmp_path / "workspace",
        artifact_output=tmp_path / "artifacts",
        max_workers=1,
        max_attempts=1,
        candidate_generation_model="test-model",
    )

    summaries = run_local_pipeline(
        submission,
        config,
        registry=registry,
    )
    artifacts = load_task_artifacts(
        TaskName.LOCAL_EFFECT,
        submission_id="test-agent",
        artifacts_dir=config.artifact_output,
    )

    assert all(not summary.has_failures for summary in summaries)
    assert artifacts.instance_ids == {INSTANCE_ID}
    assert artifacts.context[INSTANCE_ID].before_or_after == "before"
    assert artifacts.ground_truths[INSTANCE_ID].answer
    assert (config.artifact_output / "manifest.json").is_file()
    assert (config.artifact_output / "failures.json").is_file()


def test_function_parameter_format_is_bounded():
    result = format_function_parameters("x" * 21_000)

    assert result.endswith(" ...(truncated)")
    assert len(result) < 20_100

