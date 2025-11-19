# Reference script for SWE-Bench evaluation with gold predictions but without tracing
import os

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from swebench.harness.run_evaluation import main as run_evaluation_main

from execution.monkey_patch.dataset import monkey_patch_dataset
from execution.util import get_instance_ids

def main(**kwargs):
    monkey_patch_dataset()
    run_evaluation_main(
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        instance_ids=get_instance_ids(kwargs["instance_ids"]),
        predictions_path="gold",
        max_workers=kwargs["max_workers"],
        force_rebuild=False,
        cache_level="env",
        clean=False,
        open_file_limit=4096,
        run_id=f"wo_trace.gold.{os.getuid()}",
        timeout=12600,
        namespace="swebench",
        rewrite_reports=False,
        modal=False,
        instance_image_tag="latest",
        env_image_tag="latest",
        report_dir=".",
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
        help="Instance IDs to run (space separated) - 'all' for all instances; repo name(s) for all instances in the repo(s); or specific instance IDs",
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=4,
        help="Maximum number of workers (should be <= 75%% of CPU cores)",
    )
    args = parser.parse_args()
    main(**vars(args))
