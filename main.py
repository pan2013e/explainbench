import os
import ast
import sys
import libcst as cst
import libcst.matchers as m
import tempfile
from pathlib import Path, PurePosixPath
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter

from dowhen import when
from docker.models.containers import Container
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

DIR = os.path.dirname(os.path.abspath(__file__))

def read_from_docker(container: Container, path: PurePosixPath) -> str:
    """Read a file from inside a Docker container."""
    tar_stream, _ = container.get_archive(str(path))
    file_content = b""
    for chunk in tar_stream:
        file_content += chunk
    import tarfile
    import io
    with tarfile.open(fileobj=io.BytesIO(file_content)) as tar:
        member = tar.getmembers()[0]
        file = tar.extractfile(member)
        return file.read().decode('utf-8')

def get_test_entry_path(instance_id):
    if 'sympy' in instance_id:
        return PurePosixPath('/testbed/bin/test')
    else:
        raise NotImplementedError()

def rewrite_test_entry(instance_id, test_entry_code, trace_output_path):
    if 'sympy' in instance_id:
        return rewrite_test_entry_sympy(test_entry_code, trace_output_path)
    else:
        raise NotImplementedError()

def rewrite_test_entry_sympy(code, trace_output_path):
    
    class Transformer(cst.CSTTransformer):
        def leave_SimpleStatementLine(self, original_node, updated_node):
            # find assignment of `sympy.test`
            if m.matches(
                original_node,
                m.SimpleStatementLine(
                    body=[m.Assign(
                        targets=[m.AssignTarget(m.Name("ok"))],
                        value=m.Call(
                            func=m.Attribute(
                                value=m.Name("sympy"),
                                attr=m.Name("test")
                            )
                        )
                    )]
                )
            ):
                # add `from tracer import ExecutionTracer` before the assignment
                import_stmt = cst.SimpleStatementLine(
                    body=[cst.ImportFrom(
                        module=cst.Name("tracer"),
                        names=[cst.ImportAlias(name=cst.Name("ExecutionTracer"))]
                    )]
                )
                # add `ok = None`, to promote `ok` to the outer scope
                assign_ok_none = cst.SimpleStatementLine(
                    body=[cst.Assign(
                        targets=[cst.AssignTarget(cst.Name("ok"))],
                        value=cst.Name("None")
                    )]
                )
                # wrap the assignment with `with ExecutionTracer(trace_output_path) as tracer:`
                with_stmt = cst.With(
                    items=[cst.WithItem(
                        cst.Call(
                            func=cst.Name("ExecutionTracer"),
                            args=[cst.Arg(cst.SimpleString(f'"{trace_output_path}"'))]
                        ),
                        asname=cst.AsName(cst.Name("tracer"))
                    )],
                    body=cst.IndentedBlock(
                        body=[updated_node]
                    )
                )
                return cst.FlattenSentinel([import_stmt, assign_ok_none, with_stmt])
            return updated_node
    
    module = cst.parse_module(code)
    new_module = module.visit(Transformer())
    return new_module.code
    
def install_tracer(container):
    copy_to_container(container, Path(f"{DIR}/py-tracer"), PurePosixPath('/root/py-tracer'))
    exec_run_with_timeout(container, '/opt/miniconda3/envs/testbed/bin/pip install -e /root/py-tracer')
    print("Tracer installed in container")

def inject_tracer(container, test_spec, trace_output_path):
    entry_path = get_test_entry_path(test_spec.instance_id)
    entry_code = read_from_docker(container, entry_path)
    hijacked = rewrite_test_entry(test_spec.instance_id, entry_code, trace_output_path)
    with tempfile.NamedTemporaryFile("w") as f:
        f.write(hijacked)
        f.flush()
        copy_to_container(container, Path(f.name), entry_path)
    exec_run_with_timeout(container, f"chmod 755 {entry_path}")
    print(f"Tracer injected into test entry, output path: {trace_output_path}")

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
    inject_tracer(container, test_spec, "/trace_buggy.jsonl")
    buggy_test_output, buggy_timed_out, buggy_total_runtime = exec_run_with_timeout(
        container, "/bin/bash /eval.sh", timeout
    )
    with open(log_dir / "trace_buggy.jsonl", "w") as f:
        f.write(read_from_docker(container, PurePosixPath("/trace_buggy.jsonl")))
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
    with open(log_dir / "trace_fixed.jsonl", "w") as f:
        f.write(read_from_docker(container, PurePosixPath("/trace_fixed.jsonl")))

def monkey_patch():
    when(run_instance, 156).do(install_tracer)
    when(run_instance, 159).do(run_buggy_code)
    # Restore original test entry before running patched code tests
    when(run_instance, 189).do(restore_injection)
    # Skip redundant test code patching
    when(run_instance, 198).goto(206)
    # Inject tracer for fixed code
    when(run_instance, 206).do(lambda container, test_spec: inject_tracer(container, test_spec, '/trace_fixed.jsonl'))
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
