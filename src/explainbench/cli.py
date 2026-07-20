"""Command-line interface for ExplainBench."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from explainbench import __version__
from explainbench.checker import check_submission
from explainbench.evaluation.artifacts import ArtifactError
from explainbench.evaluation.checkpoints import checkpoint_path_for_output
from explainbench.evaluation.config import (
    EvaluationConfigError,
    load_evaluation_config,
    resolve_evaluation_config,
)
from explainbench.evaluation.preparation import EvaluationPreparationError
from explainbench.evaluation.registry import EvaluationMode, TaskName
from explainbench.evaluation.results import write_evaluation_result
from explainbench.evaluation.service import evaluate_submission
from explainbench.question_builders.common.locking import WorkspaceLockedError
from explainbench.question_builders.common.orchestration import (
    MissingPrerequisiteError,
    QuestionBuilderError,
    StageRunSummary,
)
from explainbench.question_builders.local.config import (
    LocalBuilderConfigError,
    load_local_builder_config,
    resolve_local_builder_config,
)
from explainbench.question_builders.local.registry import LOCAL_STAGE_REGISTRY
from explainbench.question_builders.local.service import (
    inspect_local_workspace,
    run_local_pipeline,
    run_local_stage,
)
from explainbench.question_builders.local.workspace import LocalWorkspaceError
from explainbench.submission import SubmissionValidationError, load_submission
from explainbench.submission import ValidationProfile


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="explainbench")
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    checker = subcommands.add_parser(
        "checker",
        help="validate an ExplainBench submission file",
    )
    checker.add_argument("submission", type=Path, help="path to submission JSON")

    question_builder = subcommands.add_parser(
        "question-builder",
        help="construct submission-specific effect questions",
    )
    builder_targets = question_builder.add_subparsers(
        dest="question_builder_target",
        required=True,
    )
    local_builder = builder_targets.add_parser(
        "local",
        help="construct local-effect questions",
    )
    local_actions = local_builder.add_subparsers(
        dest="local_builder_action",
        required=True,
    )

    local_run = local_actions.add_parser(
        "run",
        help="run every local-effect construction stage",
    )
    _add_local_builder_run_options(local_run, require_output=True)

    local_stage = local_actions.add_parser(
        "stage",
        help="run one local-effect construction stage",
    )
    local_stage.add_argument(
        "stage_name",
        choices=LOCAL_STAGE_REGISTRY.names,
        help="meaningful name of the stage to run",
    )
    _add_local_builder_run_options(local_stage, require_output=False)

    local_actions.add_parser(
        "stages",
        help="list local-effect stages in dependency order",
    )

    local_status = local_actions.add_parser(
        "status",
        help="inspect a local-effect build workspace",
    )
    local_status.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="builder workspace to inspect",
    )

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
    evaluate.add_argument(
        "--no-progress",
        action="store_true",
        help="disable per-task progress bars",
    )
    evaluate.add_argument(
        "--resume",
        action="store_true",
        help="reuse compatible task-instance results from an interrupted run",
    )
    return parser


def _add_local_builder_run_options(
    parser: argparse.ArgumentParser,
    *,
    require_output: bool,
) -> None:
    parser.add_argument("submission", type=Path, help="path to submission JSON")
    parser.add_argument(
        "--config",
        type=Path,
        help="path to a versioned local-builder TOML config",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="directory for checkpoints, traces, and logs",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=False,
        help=(
            "final evaluator artifact directory"
            + (" (required here or in config)" if require_output else "")
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="maximum concurrent instances; overrides config",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        help="maximum attempts for a retryable instance-stage failure",
    )
    parser.add_argument(
        "--candidate-model",
        help="candidate-expression model identifier; overrides config",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse compatible completed instance-stage checkpoints",
    )


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
        checkpoint_path = checkpoint_path_for_output(config.output)
        checkpoint_exists = checkpoint_path.is_file()
        task_names = ", ".join(task.value for task in config.selection.tasks)
        print(
            f"Preparing {len(submission.instances)} submission instance(s) "
            f"for: {task_names}",
            flush=True,
        )
        print(
            f"Evaluator: {config.evaluator.model} "
            f"({config.evaluator.num_generations} generation(s) per question)",
            flush=True,
        )
        print(f"Output: {config.output}", flush=True)
        if arguments.resume and checkpoint_exists:
            print(f"Resuming from checkpoint: {checkpoint_path}", flush=True)
        elif arguments.resume:
            print(
                f"No checkpoint found; starting a resumable run: {checkpoint_path}",
                flush=True,
            )
        else:
            print(f"Checkpoint: {checkpoint_path}", flush=True)
        print(
            "Validating submission and artifacts before model requests...",
            flush=True,
        )
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
            show_progress=(
                not arguments.no_progress and sys.stderr.isatty()
            ),
            checkpoint_path=checkpoint_path,
            resume=arguments.resume,
        )
        output = write_evaluation_result(result, config.output)
        failed = sum(task.counts.failed for task in result.tasks.values())
        if failed == 0:
            checkpoint_path.unlink(missing_ok=True)
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
    if failed:
        print(f"Checkpoint retained for retry: {checkpoint_path}")
    return 0


def _format_stage_summary(summary: StageRunSummary) -> str:
    return (
        f"{summary.stage}: completed={summary.completed}, "
        f"skipped={summary.skipped}, reused={summary.reused}, "
        f"failed={summary.failed}, blocked={summary.blocked}"
    )


def _resolved_local_builder_config(
    arguments: argparse.Namespace,
    *,
    require_output: bool,
):
    file_config = None
    source = None
    if arguments.config is not None:
        file_config, source = load_local_builder_config(arguments.config)
    return resolve_local_builder_config(
        file_config,
        source=source,
        workspace=arguments.workspace,
        output=arguments.output,
        workers=arguments.workers,
        max_attempts=arguments.max_attempts,
        candidate_generation_model=arguments.candidate_model,
        require_output=require_output,
    )


def _run_local_question_builder(arguments: argparse.Namespace) -> int:
    action = arguments.local_builder_action
    if action == "stages":
        for index, definition in enumerate(
            LOCAL_STAGE_REGISTRY.definitions,
            start=1,
        ):
            print(f"{index}. {definition.name}: {definition.description}")
        return 0

    if action == "status":
        try:
            status = inspect_local_workspace(arguments.workspace)
        except LocalWorkspaceError as error:
            print(f"Question-builder status failed: {error}", file=sys.stderr)
            return 1
        print(f"Submission ID: {status.submission_id}")
        print(f"Instances: {status.instance_count}")
        print(f"Submission fingerprint: {status.submission_fingerprint}")
        for stage_name, counts in status.stages:
            visible = ", ".join(
                f"{name}={count}" for name, count in counts.items() if count
            )
            print(f"{stage_name}: {visible or 'pending=0'}")
        if status.failures:
            print("Failures:")
            for stage_name, instance_id, message in status.failures:
                print(f"- {stage_name} / {instance_id}: {message}")
        print(
            f"Artifacts: {status.artifact_output or 'not exported'}"
        )
        return 0

    require_output = action == "run" or (
        action == "stage"
        and arguments.stage_name == "export-question-artifacts"
    )
    try:
        config = _resolved_local_builder_config(
            arguments,
            require_output=require_output,
        )
        submission = load_submission(
            arguments.submission,
            profile=ValidationProfile.QUESTION_BUILDER_LOCAL,
        )
        print(
            f"Preparing local-effect build for "
            f"{len(submission.instances)} instance(s)",
            flush=True,
        )
        print(f"Workspace: {config.workspace}", flush=True)
        if config.artifact_output is not None:
            print(f"Artifact output: {config.artifact_output}", flush=True)
        if action == "run":
            summaries = run_local_pipeline(
                submission,
                config,
                resume=arguments.resume,
            )
        else:
            summaries = (
                run_local_stage(
                    arguments.stage_name,
                    submission,
                    config,
                    resume=arguments.resume,
                ),
            )
    except LocalBuilderConfigError as error:
        print(f"Local question-builder configuration is invalid: {error}", file=sys.stderr)
        return 1
    except SubmissionValidationError as error:
        print("Submission is invalid", file=sys.stderr)
        for issue in error.issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    except (
        LocalWorkspaceError,
        WorkspaceLockedError,
        MissingPrerequisiteError,
        QuestionBuilderError,
        OSError,
        ValueError,
    ) as error:
        print(f"Local question builder failed: {error}", file=sys.stderr)
        return 1

    for summary in summaries:
        print(_format_stage_summary(summary))
    if any(summary.has_failures for summary in summaries):
        print(
            "Local question builder did not complete; checkpoints and logs were retained",
            file=sys.stderr,
        )
        return 1
    print("Local question building complete")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ExplainBench CLI and return a process exit status."""

    arguments = _build_parser().parse_args(argv)
    if arguments.command == "checker":
        return _run_checker(arguments.submission)
    if arguments.command == "question-builder":
        if arguments.question_builder_target == "local":
            return _run_local_question_builder(arguments)
        raise AssertionError(
            f"unhandled question-builder target: "
            f"{arguments.question_builder_target}"
        )
    if arguments.command == "evaluate":
        return _run_evaluate(arguments)

    raise AssertionError(f"unhandled command: {arguments.command}")
