"""Run mocked lite evaluation only with the installed wheel."""

from __future__ import annotations

import shutil

from conftest import CleanWheel


def test_clean_evaluation(clean_wheel: CleanWheel):
    submission = clean_wheel.run_directory / "evaluation-submission.json"
    shutil.copyfile(
        clean_wheel.source_root / "examples" / "submission-lite.json",
        submission,
    )
    result = clean_wheel.run_python(
        """
import sys

from pydantic import BaseModel

from explainbench.evaluation.service import evaluate_submission
from explainbench.submission import load_submission


class FakeEvaluator:
    token_usage = {
        "completion_tokens": 3,
        "prompt_tokens": 30,
        "total_tokens": 33,
    }

    def infer(self, messages, schema: type[BaseModel]):
        return [schema.model_validate({"answer": ["a"]})]


submission = load_submission(sys.argv[1])
result = evaluate_submission(
    submission,
    mode="lite",
    model_id="clean-wheel-fake",
    num_generations=1,
    workers=1,
    generation_workers=1,
    temperature=0.0,
    top_p=1.0,
    max_tokens=32,
    max_retries=1,
    inference_model=FakeEvaluator(),
)
assert len(result.tasks) == 2
assert all(task.counts.evaluated == 3 for task in result.tasks.values())
assert all(not task.failures for task in result.tasks.values())
print("clean evaluation passed")
""",
        str(submission),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "clean evaluation passed"
