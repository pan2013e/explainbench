import os
import sys

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from swebench.harness.run_evaluation import main as run_evaluation_main

from execution.monkey_patch.dataset import monkey_patch_dataset
from execution.monkey_patch.inspect import monkey_patch_execution
from execution.util import all_instances, prepare_tracer

def main(**kwargs):
    monkey_patch_dataset()
    monkey_patch_execution(**kwargs)
    prepare_tracer()
    for key in ['bp_file', 'pre_bp_line', 'post_bp_line', 'expr', 'pre_count', 'post_count', 'inspector_mode']:
        kwargs.pop(key, None)
    run_evaluation_main(
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        open_file_limit=4096,
        timeout=3600,
        force_rebuild=False,
        cache_level="env",
        clean=False,
        namespace="swebench",
        instance_image_tag="latest",
        env_image_tag="latest",
        rewrite_reports=False,
        modal=False,
        report_dir=".",
        **kwargs
    )

if __name__ == "__main__":
    parser = ArgumentParser(
        description="Run evaluation harness for the given dataset and predictions.",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--instance_ids",
        nargs="+",
        type=str,
        help="Instance IDs to run (space separated)",
    )
    parser.add_argument(
        "-p",
        "--predictions_path",
        type=str,
        help="Path to predictions file - if 'gold', uses gold predictions",
        required=True,
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=4,
        help="Maximum number of workers (should be <= 75%% of CPU cores)",
    )
    parser.add_argument(
        "-id", "--run_id", type=str, required=True, help="Run ID - identifies the run"
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
        "--pre-count", type=int, default=1,
    )
    parser.add_argument(
        "--post-count", type=int, default=1,
    )
    parser.add_argument(
        "--inspector-mode", type=str, choices=['before', 'after'], default='before',
    )
    sys.argv = ["swebench.harness.run_evaluation",
            "--predictions_path", "gold",
            "--max_workers", "1",
            "--instance_ids", "astropy__astropy-7166",
            "--run_id", f"inspect.validate-gold.{os.getuid()}",
            "--bp-file", "/testbed/astropy/utils/misc.py",
            "--pre-bp-line", "530",
            "--pre-count", "10",
            "--post-bp-line", "526",
            "--post-count", "10",
            "--expr", "dct"]
    args = parser.parse_args()
    main(**vars(args))
