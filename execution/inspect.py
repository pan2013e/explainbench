import os

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from swebench.harness.run_evaluation import main as run_evaluation_main

from execution.monkey_patch.dataset import monkey_patch_dataset
from execution.monkey_patch.inspect import monkey_patch_execution
from execution.util import prepare_tracer, get_predictions_path

def inspect(**kwargs):
    monkey_patch_dataset()
    monkey_patch_execution(**kwargs)
    prepare_tracer()
    run_evaluation_main(
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        instance_ids=[kwargs["instance_id"]],
        predictions_path=get_predictions_path(kwargs["agent"]),
        max_workers=0,
        force_rebuild=False,
        cache_level="env",
        clean=False,
        open_file_limit=4096,
        run_id=f"inspect.{kwargs["agent"]}.{os.getuid()}",
        timeout=10800,
        namespace="swebench",
        rewrite_reports=False,
        modal=False,
        instance_image_tag="latest",
        env_image_tag="latest",
        report_dir=".",
    )
    
def main(args=None):
    parser = ArgumentParser(
        description="Run evaluation harness for the given dataset and predictions.",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
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
        "--pre-count", type=int, default=1,
    )
    parser.add_argument(
        "--post-count", type=int, default=1,
    )
    parser.add_argument(
        "--inspector-mode", type=str, choices=['before', 'after'], default='before',
    )
    args = parser.parse_args(args)
    inspect(**vars(args))

if __name__ == "__main__":
    import sys
    main(sys.argv)
