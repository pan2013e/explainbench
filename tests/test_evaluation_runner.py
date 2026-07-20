from pydantic import BaseModel

from explainbench.evaluation.predictions import AnswerPrediction
from explainbench.evaluation.preparation import prepare_evaluation
from explainbench.evaluation.registry import TaskName, resolve_task_selection
from explainbench.evaluation.runner import run_evaluation
from explainbench.schemas import Submission


INSTANCE_ID = "astropy__astropy-12907"


def make_prepared_lite_evaluation():
    submission = Submission.model_validate(
        {
            "submission_id": "test-agent",
            "instances": [
                {
                    "instance_id": INSTANCE_ID,
                    "explanation": "The changed expression corresponds to option d.",
                }
            ],
        }
    )
    return prepare_evaluation(submission, resolve_task_selection(mode="lite"))


class CorrectModel:
    token_usage = {
        "completion_tokens": 2,
        "prompt_tokens": 20,
        "total_tokens": 22,
    }

    def infer(
        self,
        messages: str | list[dict[str, str]],
        schema: type[BaseModel],
    ) -> list[BaseModel]:
        return [schema.model_validate({"answer": ["d"]})]


class PartiallyFailingModel(CorrectModel):
    def infer(
        self,
        messages: str | list[dict[str, str]],
        schema: type[BaseModel],
    ) -> list[BaseModel]:
        if isinstance(messages, str) and "Masked Test:" in messages:
            raise RuntimeError("simulated provider failure")
        return super().infer(messages, schema)


def test_runner_generates_and_scores_every_prepared_task():
    result = run_evaluation(make_prepared_lite_evaluation(), CorrectModel(), workers=2)

    assert tuple(result.tasks) == (TaskName.E2E_INTENT, TaskName.LOCAL_INTENT)
    assert result.token_usage["total_tokens"] == 22
    for task_result in result.tasks.values():
        instance = task_result.instances[INSTANCE_ID]
        assert instance.predictions == (AnswerPrediction(answer=["d"]),)
        assert instance.scores == (1.0,)
        assert not task_result.failures
        assert not task_result.skipped_instance_ids


def test_runner_preserves_completed_tasks_when_an_instance_fails():
    result = run_evaluation(
        make_prepared_lite_evaluation(),
        PartiallyFailingModel(),
        workers=2,
    )

    e2e = result.tasks[TaskName.E2E_INTENT]
    local = result.tasks[TaskName.LOCAL_INTENT]
    assert not e2e.instances
    assert e2e.failures == {
        INSTANCE_ID: "RuntimeError: simulated provider failure"
    }
    assert local.instances[INSTANCE_ID].scores == (1.0,)
    assert not local.failures


def test_runner_requires_a_positive_worker_count():
    try:
        run_evaluation(make_prepared_lite_evaluation(), CorrectModel(), workers=0)
    except ValueError as error:
        assert str(error) == "workers must be at least 1"
    else:
        raise AssertionError("run_evaluation accepted workers=0")


def test_runner_reports_progress_for_each_selected_task(monkeypatch):
    progress_calls = []

    class FakeProgress:
        def __init__(self, iterable, **kwargs):
            self.iterable = iterable
            self.kwargs = kwargs
            self.postfixes = []
            self.closed = False
            progress_calls.append(self)

        def __iter__(self):
            return iter(self.iterable)

        def set_postfix(self, **kwargs):
            self.postfixes.append(kwargs)

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        "explainbench.evaluation.runner.tqdm",
        FakeProgress,
    )

    run_evaluation(
        make_prepared_lite_evaluation(),
        CorrectModel(),
        workers=2,
        show_progress=True,
    )

    assert [call.kwargs["desc"] for call in progress_calls] == [
        "Evaluating e2e.intent",
        "Evaluating local.intent",
    ]
    assert all(call.kwargs["total"] == 1 for call in progress_calls)
    assert all(call.kwargs["unit"] == "instance" for call in progress_calls)
    assert all(call.postfixes[-1]["completed"] == 1 for call in progress_calls)
    assert all(call.postfixes[-1]["failed"] == 0 for call in progress_calls)
    assert all(call.closed for call in progress_calls)
