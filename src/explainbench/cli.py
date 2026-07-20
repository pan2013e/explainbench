"""Command-line interface for ExplainBench."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from explainbench import __version__
from explainbench.checker import check_submission
from explainbench.evaluation.artifacts import ArtifactError
from explainbench.evaluation.preparation import EvaluationPreparationError
from explainbench.evaluation.registry import EvaluationMode, TaskName
from explainbench.evaluation.results import write_evaluation_result
from explainbench.evaluation.service import (
    DEFAULT_EVALUATOR_MODEL,
    evaluate_submission,
)
from explainbench.submission import SubmissionValidationError, load_submission


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="explainbench")
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    checker = subcommands.add_parser(
        "checker",
        help="validate an ExplainBench submission file",
    )
    checker.add_argument("submission", type=Path, help="path to submission JSON")

    evaluate = subcommands.add_parser(
        "evaluate",
        help="evaluate explanations in an ExplainBench submission",
    )
    evaluate.add_argument("submission", type=Path, help="path to submission JSON")
    selection = evaluate.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--mode",
        choices=[mode.value for mode in EvaluationMode],
        help="evaluate a predefined task set",
    )
    selection.add_argument(
        "--task",
        action="append",
        choices=[task.value for task in TaskName],
        help="evaluate one task; repeat to select multiple tasks",
    )
    evaluate.add_argument(
        "--model",
        default=DEFAULT_EVALUATOR_MODEL,
        help="evaluator model identifier",
    )
    evaluate.add_argument(
        "--num-generations",
        type=int,
        default=5,
        help="model answers requested per task instance (default: 5)",
    )
    evaluate.add_argument(
        "--workers",
        type=int,
        default=10,
        help="maximum concurrent instance evaluations (default: 10)",
    )
    evaluate.add_argument(
        "--artifacts-dir",
        type=Path,
        help="question-artifact root required by effect tasks",
    )
    evaluate.add_argument(
        "--output",
        type=Path,
        required=True,
        help="path for the versioned evaluation result JSON",
    )
    return parser


def _run_checker(submission: Path) -> int:
    try:
        summary = check_submission(submission)
    except SubmissionValidationError as error:
        print("Submission is invalid", file=sys.stderr)
        for issue in error.issues:
            print(f"- {issue}", file=sys.stderr)
        return 1

    print("Submission is valid")
    print(f"Submission ID: {summary.submission_id}")
    print(f"Instances: {summary.instance_count}")
    print(f"Explanations: {summary.explanation_count}")
    print(f"Patches: {summary.patch_count}")
    return 0


def _run_evaluate(arguments: argparse.Namespace) -> int:
    try:
        submission = load_submission(arguments.submission)
        result = evaluate_submission(
            submission,
            mode=arguments.mode,
            tasks=arguments.task,
            model_id=arguments.model,
            num_generations=arguments.num_generations,
            workers=arguments.workers,
            artifacts_dir=arguments.artifacts_dir,
        )
        output = write_evaluation_result(result, arguments.output)
    except SubmissionValidationError as error:
        print("Submission is invalid", file=sys.stderr)
        for issue in error.issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    except (ArtifactError, EvaluationPreparationError, ValueError, OSError) as error:
        print(f"Evaluation failed: {error}", file=sys.stderr)
        return 1

    evaluated = sum(task.counts.evaluated for task in result.tasks.values())
    failed = sum(task.counts.failed for task in result.tasks.values())
    print("Evaluation complete")
    print(f"Submission ID: {result.submission_id}")
    print(f"Tasks: {', '.join(task.value for task in result.selection.tasks)}")
    print(f"Evaluated task instances: {evaluated}")
    print(f"Failed task instances: {failed}")
    print(f"Results: {output}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ExplainBench CLI and return a process exit status."""

    arguments = _build_parser().parse_args(argv)
    if arguments.command == "checker":
        return _run_checker(arguments.submission)
    if arguments.command == "evaluate":
        return _run_evaluate(arguments)

    raise AssertionError(f"unhandled command: {arguments.command}")
