from explainbench.evaluation.predictions import AnswerPrediction
from explainbench.evaluation.config import EvaluatorSettings
from explainbench.evaluation.preparation import prepare_evaluation
from explainbench.evaluation.registry import TaskName, resolve_task_selection
from explainbench.evaluation.results import build_evaluation_result
from explainbench.evaluation.runner import (
    EvaluationRunResult,
    InstanceRunResult,
    TaskRunResult,
)
from explainbench.schemas import Submission


INSTANCE_IDS = ("astropy__astropy-12907", "astropy__astropy-13033")


def test_result_statistics_use_per_instance_generation_means():
    submission = Submission.model_validate(
        {
            "submission_id": "test-agent",
            "instances": [
                {
                    "instance_id": instance_id,
                    "explanation": f"Explanation for {instance_id}",
                }
                for instance_id in INSTANCE_IDS
            ],
        }
    )
    prepared = prepare_evaluation(
        submission,
        resolve_task_selection(tasks=["local.intent"]),
    )
    instances = {
        INSTANCE_IDS[0]: InstanceRunResult(
            predictions=(AnswerPrediction(answer=["d"]),) * 2,
            scores=(1.0, 1.0),
        ),
        INSTANCE_IDS[1]: InstanceRunResult(
            predictions=(AnswerPrediction(answer=["d"]),) * 2,
            scores=(0.0, 0.0),
        ),
    }
    run = EvaluationRunResult(
        tasks={
            TaskName.LOCAL_INTENT: TaskRunResult(
                task=TaskName.LOCAL_INTENT,
                instances=instances,
                skipped_instance_ids=(),
                failures={},
            )
        },
        token_usage={
            "completion_tokens": 4,
            "prompt_tokens": 20,
            "total_tokens": 24,
        },
    )

    result = build_evaluation_result(
        prepared,
        run,
        settings=EvaluatorSettings(
            model="test-model",
            num_generations=2,
            instance_workers=2,
            generation_workers=2,
            temperature=0.5,
            top_p=0.9,
            max_tokens=1024,
            max_retries=3,
        ),
    )

    task = result.tasks[TaskName.LOCAL_INTENT]
    assert task.statistics.mean == 0.5
    assert task.statistics.sem == 0.5
    assert task.counts.model_dump() == {
        "submitted": 2,
        "evaluated": 2,
        "skipped": 0,
        "failed": 0,
    }
