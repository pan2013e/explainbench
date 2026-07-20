import os

from argparse import (
    ArgumentDefaultsHelpFormatter,
    ArgumentParser,
    BooleanOptionalAction,
)
from pathlib import Path

from swebench.harness.run_evaluation import main as run_evaluation_main

from execution.monkey_patch.track import monkey_patch_execution
from execution.util import prepare_tracer, get_instance_ids, get_predictions_path


def run_tracking(**kwargs):
    """Run the existing lightweight tracking workflow with explicit inputs."""

    monkey_patch_execution(
        agent=kwargs["agent"],
        allowed_qualnames_path=(
            str(kwargs["allowed_qualnames_path"])
            if kwargs["allowed_qualnames_path"] is not None
            else None
        ),
    )
    prepare_tracer()
    predictions_path = kwargs["predictions_path"]
    if predictions_path is None:
        predictions_path = get_predictions_path(kwargs["agent"])
    run_id = kwargs["run_id"] or f"track.{kwargs['agent']}.{os.getuid()}"
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
        report_dir=str(kwargs["report_dir"]),
    )


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Run SWE-bench tests with lightweight patched-function tracking.",
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
        "--allowed-qualnames-path",
        type=Path,
        help=(
            "Qualified-name whitelist JSON. If omitted, use "
            "execution/allowed_qualnames.json."
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
    parser.add_argument("--timeout", type=int, default=1800)
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
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    run_tracking(**vars(args))


if __name__ == "__main__":
    main()
