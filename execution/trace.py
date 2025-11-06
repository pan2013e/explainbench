import os
import sys

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from swebench.harness.run_evaluation import main as run_evaluation_main

from execution.monkey_patch.trace import monkey_patch
from execution.util import all_instances, prepare_tracer, instances_by_repo

def main(**kwargs):
    monkey_patch()
    prepare_tracer()
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
    sys.argv = ["swebench.harness.run_evaluation",
            "--predictions_path", "gold",
            "--max_workers", "10",
            "--instance_ids", *instances_by_repo(['astropy', 'django']),
            "--run_id", f"trace.validate-gold.{os.getuid()}"]
    args = parser.parse_args()
    main(**vars(args))
