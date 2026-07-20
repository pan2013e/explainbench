"""Command-line interface for ExplainBench."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from explainbench import __version__
from explainbench.checker import check_submission
from explainbench.evaluation.artifacts import ArtifactError
from explainbench.evaluation.config import (
    EvaluationConfigError,
    load_evaluation_config,
    resolve_evaluation_config,
)
from explainbench.evaluation.preparation import EvaluationPreparationError
from explainbench.evaluation.registry import EvaluationMode, TaskName
from explainbench.evaluation.results import write_evaluation_result
from explainbench.evaluation.service import evaluate_submission
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
    evaluate.add_argument(
        "--config",
        type=Path,
        help="path to a versioned evaluation TOML config",
    )
    selection = evaluate.add_mutually_exclusive_group()
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
        help="evaluator model identifier; overrides config",
    )
    evaluate.add_argument(
        "--num-generations",
        type=int,
        help="model answers requested per task instance; overrides config",
    )
    evaluate.add_argument(
        "--workers",
        type=int,
        help="maximum concurrent instances; overrides config",
    )
    evaluate.add_argument(
        "--generation-workers",
        type=int,
        help="maximum concurrent generations per instance; overrides config",
    )
    evaluate.add_argument(
        "--temperature",
        type=float,
        help="evaluator sampling temperature; overrides config",
    )
    evaluate.add_argument(
        "--top-p",
        type=float,
        help="evaluator nucleus-sampling probability; overrides config",
    )
    evaluate.add_argument(
        "--max-tokens",
        type=int,
        help="maximum evaluator response tokens; overrides config",
    )
    evaluate.add_argument(
        "--max-retries",
        type=int,
        help="maximum attempts for each model request; overrides config",
    )
    evaluate.add_argument(
        "--artifacts-dir",
        type=Path,
        help="question-artifact root required by effect tasks; overrides config",
    )
    evaluate.add_argument(
        "--env-file",
        type=Path,
        help="dotenv credentials file; overrides config",
    )
    evaluate.add_argument(
        "--output",
        type=Path,
        help="result JSON path; required here or in config",
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
        file_config = None
        config_source = None
        if arguments.config is not None:
            file_config, config_source = load_evaluation_config(arguments.config)
        config = resolve_evaluation_config(
            file_config,
            source=config_source,
            mode=arguments.mode,
            tasks=arguments.task,
            model=arguments.model,
            num_generations=arguments.num_generations,
            instance_workers=arguments.workers,
            generation_workers=arguments.generation_workers,
            temperature=arguments.temperature,
            top_p=arguments.top_p,
            max_tokens=arguments.max_tokens,
            max_retries=arguments.max_retries,
            output=arguments.output,
            artifacts_dir=arguments.artifacts_dir,
            env_file=arguments.env_file,
        )
        submission = load_submission(arguments.submission)
        selected_mode = config.selection.mode
        selected_tasks = None if selected_mode is not None else config.selection.tasks
        result = evaluate_submission(
            submission,
            mode=selected_mode,
            tasks=selected_tasks,
            model_id=config.evaluator.model,
            num_generations=config.evaluator.num_generations,
            workers=config.evaluator.instance_workers,
            generation_workers=config.evaluator.generation_workers,
            temperature=config.evaluator.temperature,
            top_p=config.evaluator.top_p,
            max_tokens=config.evaluator.max_tokens,
            max_retries=config.evaluator.max_retries,
            artifacts_dir=config.artifacts_dir,
            env_file=config.env_file,
        )
        output = write_evaluation_result(result, config.output)
    except EvaluationConfigError as error:
        print(f"Evaluation configuration is invalid: {error}", file=sys.stderr)
        return 1
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
