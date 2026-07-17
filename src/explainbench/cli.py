"""Command-line interface for ExplainBench."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from explainbench import __version__
from explainbench.checker import check_submission
from explainbench.submission import SubmissionValidationError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="explainbench")
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    checker = subcommands.add_parser(
        "checker",
        help="validate an ExplainBench submission file",
    )
    checker.add_argument("submission", type=Path, help="path to submission JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ExplainBench CLI and return a process exit status."""

    arguments = _build_parser().parse_args(argv)
    if arguments.command == "checker":
        try:
            summary = check_submission(arguments.submission)
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

    raise AssertionError(f"unhandled command: {arguments.command}")
