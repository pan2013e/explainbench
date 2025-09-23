import os
import sys
from pathlib import Path, PurePosixPath
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter

from dowhen import when
from swebench.harness.run_evaluation import (
    run_instance,
    main as run_evaluation_main
)
from swebench.harness.docker_utils import (
    copy_to_container,
    exec_run_with_timeout
)
from swebench.harness.utils import (
    EvaluationError,
    str2bool,
    optional_str,
)

from util import copy_directory_from_docker, TestCodeInjector

DIR = os.path.dirname(os.path.abspath(__file__))

def get_test_entry_path(instance_id):
    if 'sympy' in instance_id:
        return PurePosixPath('/testbed/bin/test')
    else:
        raise NotImplementedError()

def install_tracer(container):
    copy_to_container(container, Path(f"{DIR}/py-tracer"), PurePosixPath('/root/py-tracer'))
    exec_run_with_timeout(container, '/opt/miniconda3/envs/testbed/bin/pip install -e /root/py-tracer')
    print("Tracer installed in container")

def inject_tracer(container, test_spec, prefix):
    injector = TestCodeInjector(container, test_spec.instance_id)
    injector(prefix)

def restore_injection(container, test_spec):
    entry_path = get_test_entry_path(test_spec.instance_id)
    exec_run_with_timeout(container, f"git restore {entry_path}")
    print("Test entry restored")

def run_buggy_code(log_dir, test_spec, logger, instance_id, container, timeout):
    # 1. Patch test code
    eval_file = Path(log_dir / "eval.sh")
    eval_file.write_text(test_spec.eval_script)
    logger.info(
        f"Eval script for {instance_id} written to {eval_file}; copying to container..."
    )
    copy_to_container(container, eval_file, PurePosixPath("/eval.sh"))
    # 2. Run buggy code and retrieve buggy code execution trace
    inject_tracer(container, test_spec, "/buggy_traces")
    buggy_test_output, buggy_timed_out, buggy_total_runtime = exec_run_with_timeout(
        container, "/bin/bash /eval.sh", timeout
    )
    copy_directory_from_docker(container, PurePosixPath("/buggy_traces"), log_dir)
    test_output_path = log_dir / "test_output_buggy.txt"
    logger.info(f"Test runtime (BUGGY): {buggy_total_runtime:_.2f} seconds")
    with open(test_output_path, "w") as f:
        f.write(buggy_test_output)
        logger.info(f"Test output (BUGGY) for {instance_id} written to {test_output_path}")
        if buggy_timed_out:
            f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
            raise EvaluationError(
                instance_id,
                f"Test (BUGGY) timed out after {timeout} seconds.",
                logger,
            )

def retrieve_fixed_trace(log_dir, container):
    breakpoint()   
    copy_directory_from_docker(container, PurePosixPath("/fixed_traces"), log_dir)

def monkey_patch():
    when(run_instance, 156).do(install_tracer)
    when(run_instance, 159).do(run_buggy_code)
    # Restore original test entry before running patched code tests
    when(run_instance, 189).do(restore_injection)
    # Skip redundant test code patching
    when(run_instance, 198).goto(206)
    # Inject tracer for fixed code
    when(run_instance, 206).do(lambda container, test_spec: inject_tracer(container, test_spec, '/fixed_traces'))
    # Retrieve fixed code execution trace
    when(run_instance, 209).do(retrieve_fixed_trace)
    # Redirect fixed code test output path
    when(run_instance, 211).do("test_output_path = log_dir / 'test_output_fixed.txt'")
    # Restore original test entry after running patched code tests
    when(run_instance, 223).do(restore_injection)
    print('Monkey patch applied')
    
def main(**kwargs):
    monkey_patch()
    run_evaluation_main(**kwargs)

if __name__ == "__main__":
    parser = ArgumentParser(
        description="Run evaluation harness for the given dataset and predictions.",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    # Common args
    parser.add_argument(
        "-d",
        "--dataset_name",
        default="SWE-bench/SWE-bench_Verified",
        type=str,
        help="Name of dataset or path to JSON file.",
    )
    parser.add_argument(
        "-s", "--split", type=str, default="test", help="Split of the dataset"
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
    # Local execution args
    parser.add_argument(
        "--max_workers",
        type=int,
        default=4,
        help="Maximum number of workers (should be <= 75%% of CPU cores)",
    )
    parser.add_argument(
        "--open_file_limit", type=int, default=4096, help="Open file limit"
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=1_800,
        help="Timeout (in seconds) for running tests for each instance",
    )
    parser.add_argument(
        "--force_rebuild",
        type=str2bool,
        default=False,
        help="Force rebuild of all images",
    )
    parser.add_argument(
        "--cache_level",
        type=str,
        choices=["none", "base", "env", "instance"],
        help="Cache level - remove images above this level",
        default="env",
    )
    # if clean is true then we remove all images that are above the cache level
    # if clean is false, we only remove images above the cache level if they don't already exist
    parser.add_argument(
        "--clean", type=str2bool, default=False, help="Clean images above cache level"
    )
    parser.add_argument(
        "-id", "--run_id", type=str, required=True, help="Run ID - identifies the run"
    )
    parser.add_argument(
        "-n",
        "--namespace",
        type=optional_str,
        default="swebench",
        help='Namespace for images. (use "none" to use no namespace)',
    )
    parser.add_argument(
        "--instance_image_tag", type=str, default="latest", help="Instance image tag"
    )
    parser.add_argument(
        "--env_image_tag", type=str, default="latest", help="Environment image tag"
    )
    parser.add_argument(
        "--rewrite_reports",
        type=str2bool,
        default=False,
        help="Doesn't run new instances, only writes reports for instances with existing test outputs",
    )
    parser.add_argument(
        "--report_dir", type=str, default=".", help="Directory to write reports to"
    )
    # Modal execution args
    parser.add_argument("--modal", type=str2bool, default=False, help="Run on Modal")
    sys.argv = ["swebench.harness.run_evaluation",
            "--predictions_path", "gold",
            "--max_workers", "1",
            "--instance_ids", "sympy__sympy-20590",
            "--report_dir", "results",
            "--run_id", "validate-gold"]
    args = parser.parse_args()
    main(**vars(args))
