import os

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from swebench.harness.run_evaluation import main as run_evaluation_main

from execution.monkey_patch.dataset import monkey_patch_dataset
from execution.monkey_patch.track import monkey_patch_execution
from execution.util import prepare_tracer, get_instance_ids, get_predictions_path

def main(**kwargs):
    monkey_patch_dataset()
    monkey_patch_execution()
    prepare_tracer()
    run_evaluation_main(
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        instance_ids=get_instance_ids(kwargs["instance_ids"]),
        predictions_path=get_predictions_path(kwargs["agent"]),
        max_workers=kwargs["max_workers"],
        force_rebuild=False,
        cache_level="env",
        clean=False,
        open_file_limit=4096,
        run_id=f"track.{kwargs["agent"]}.{os.getuid()}",
        timeout=10800,
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
        "--agent",
        type=str,
        help="Agent submission ID - if 'gold', uses gold predictions",
        required=True,
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=4,
        help="Maximum number of workers (should be <= 75%% of CPU cores)",
    )
    args = parser.parse_args()
    main(**vars(args))
