import os

from argparse import (
    ArgumentDefaultsHelpFormatter,
    ArgumentParser,
    BooleanOptionalAction,
)
from pathlib import Path

from swebench.harness.run_evaluation import main as run_evaluation_main

from execution.monkey_patch.trace import monkey_patch_execution
from execution.util import prepare_tracer, get_instance_ids, get_predictions_path


def run_tracing(**kwargs):
    """Run the existing detailed tracing workflow with explicit inputs."""

    work_dir = Path(kwargs["work_dir"]).expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    report_dir = Path(kwargs["report_dir"]).expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    allowed_functions_path = kwargs["allowed_functions_path"]
    if allowed_functions_path is not None:
        allowed_functions_path = Path(allowed_functions_path).expanduser().resolve()
    monkey_patch_execution(
        agent=kwargs["agent"],
        allowed_functions_path=(
            str(allowed_functions_path)
            if allowed_functions_path is not None
            else None
        ),
    )
    prepare_tracer()
    predictions_path = kwargs["predictions_path"]
    if predictions_path is None:
        predictions_path = get_predictions_path(kwargs["agent"])
    predictions_path = Path(predictions_path).expanduser().resolve()
    run_id = kwargs["run_id"] or f"trace.{kwargs['agent']}.{os.getuid()}"
    original_work_dir = Path.cwd()
    try:
        os.chdir(work_dir)
        run_evaluation_main(
            dataset_name=kwargs["dataset_name"],
            split=kwargs["split"],
            instance_ids=get_instance_ids(kwargs["instance_ids"]),
            predictions_path=str(predictions_path),
            max_workers=kwargs["max_workers"],
            force_rebuild=kwargs["force_rebuild"],
            cache_level=kwargs["cache_level"],
            clean=kwargs["clean"],
            open_file_limit=kwargs["open_file_limit"],
            run_id=run_id,
            timeout=kwargs["timeout"],
            namespace=kwargs["namespace"],
            rewrite_reports=kwargs["rewrite_reports"],
            modal=kwargs["modal"],
            instance_image_tag=kwargs["instance_image_tag"],
            env_image_tag=kwargs["env_image_tag"],
            report_dir=str(report_dir),
        )
    finally:
        os.chdir(original_work_dir)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Run SWE-bench tests with detailed state tracing.",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--instance-ids",
        "--instance_ids",
        nargs="+",
        required=True,
        help=(
            "Instance IDs to run; use 'all', repository names, or explicit "
            "SWE-bench instance IDs."
        ),
    )
    parser.add_argument(
        "--agent",
        required=True,
        help="Submission ID; use 'gold' for developer patches.",
    )
    parser.add_argument(
        "--predictions-path",
        type=Path,
        help=(
            "Explicit SWE-bench predictions JSON. If omitted, resolve the "
            "historical {agent}.json location."
        ),
    )
    parser.add_argument(
        "--allowed-functions-path",
        type=Path,
        help=(
            "Detailed-trace function whitelist JSON. If omitted, use "
            "execution/allowed_functions.json."
        ),
    )
    parser.add_argument(
        "--run-id",
        help="SWE-bench run ID; defaults to the historical agent/UID form.",
    )
    parser.add_argument(
        "--max-workers",
        "--max_workers",
        type=int,
        default=4,
        help="Maximum number of concurrent SWE-bench instances.",
    )
    parser.add_argument("--timeout", type=int, default=21600)
    parser.add_argument(
        "--dataset-name",
        default="SWE-bench/SWE-bench_Verified",
    )
    parser.add_argument("--split", default="test")
    parser.add_argument(
        "--force-rebuild",
        action=BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--cache-level", default="env")
    parser.add_argument(
        "--clean",
        action=BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--open-file-limit", type=int, default=4096)
    parser.add_argument("--namespace", default="swebench")
    parser.add_argument(
        "--rewrite-reports",
        action=BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--modal",
        action=BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--instance-image-tag", default="latest")
    parser.add_argument("--env-image-tag", default="latest")
    parser.add_argument("--report-dir", type=Path, default=Path("."))
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("."),
        help="Working directory that contains SWE-bench logs for this run.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    run_tracing(**vars(args))


if __name__ == "__main__":
    main()
