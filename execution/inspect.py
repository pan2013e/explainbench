import os
from pathlib import Path

from argparse import (
    ArgumentDefaultsHelpFormatter,
    ArgumentParser,
    BooleanOptionalAction,
)
from swebench.harness.run_evaluation import main as run_evaluation_main

from execution.monkey_patch.inspect import monkey_patch_execution
from execution.util import prepare_tracer, get_predictions_path

def inspect(**kwargs):
    monkey_patch_execution(**kwargs)
    prepare_tracer()
    predictions_path = kwargs.get("predictions_path")
    if predictions_path is None:
        predictions_path = get_predictions_path(kwargs["agent"])
    run_id = kwargs.get("run_id") or (
        f"inspect.{kwargs['agent']}.{os.getuid()}.{kwargs['expr_id']}"
    )
    run_evaluation_main(
        dataset_name=kwargs["dataset_name"],
        split=kwargs["split"],
        instance_ids=[kwargs["instance_id"]],
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
    
def main(args=None):
    parser = ArgumentParser(
        description="Run evaluation harness for the given dataset and predictions.",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--instance-id",
        "--instance_id",
        type=str,
        help="Instance ID to run",
        required=True,
    )
    parser.add_argument(
        "--agent",
        type=str,
        help="Agent submission ID - if 'gold', uses gold predictions",
        required=True,
    )
    parser.add_argument(
        "--bp-file", type=str, required=True, help="Path to source file with breakpoint",
    )
    parser.add_argument(
        "--pre-bp-line", type=int, required=True, help="Line number of breakpoint before the patch"
    )
    parser.add_argument(
        "--post-bp-line", type=int, required=True, help="Line number of breakpoint after the patch"
    )
    parser.add_argument(
        "--expr", type=str, required=True, help="Expression to inspect at breakpoint"
    )
    parser.add_argument(
        "--expr-id", type=int, default=0,
    )
    parser.add_argument(
        "--pre-count", type=int, default=1,
    )
    parser.add_argument(
        "--post-count", type=int, default=1,
    )
    parser.add_argument(
        "--inspector-mode", type=str, choices=['before', 'after'], default='before',
    )
    parser.add_argument(
        "--bp-func", type=str, default=None, help="Function name where breakpoint is set",
    )
    parser.add_argument(
        "--predictions-path",
        type=Path,
        help="Explicit SWE-bench predictions JSON for this agent.",
    )
    parser.add_argument(
        "--run-id",
        help="Explicit SWE-bench inspection run ID.",
    )
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument(
        "--dataset-name",
        default="SWE-bench/SWE-bench_Verified",
    )
    parser.add_argument("--split", default="test")
    parser.add_argument("--namespace", default="swebench")
    parser.add_argument("--max-workers", type=int, default=0)
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
    args = parser.parse_args(args)
    inspect(**vars(args))

if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
