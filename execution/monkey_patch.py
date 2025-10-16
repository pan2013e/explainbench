import os
from pathlib import Path, PurePosixPath

from dowhen import when
from swebench.harness.run_evaluation import run_instance
from swebench.harness.docker_utils import (
    copy_to_container,
    exec_run_with_timeout
)
from swebench.harness.utils import EvaluationError

from execution.util import copy_directory_from_docker

DIR = os.path.dirname(os.path.abspath(__file__))

def install_tracer(container, logger):
    copy_to_container(container, Path(f"{DIR}/../py-tracer"), PurePosixPath('/root/py-tracer'))
    logger.info("Tracer code copied to container")

def get_injected_script(instance_id: str, mode: str):
    if 'django' in instance_id:
        raise NotImplementedError("Django test suites are not supported yet.")
    elif 'sphinx' in instance_id:
        raise NotImplementedError("Sphinx test suites are not supported yet.")
    elif 'sympy' in instance_id:
        return (
            'source /opt/miniconda3/bin/activate\n'
            'conda activate testbed\n'
            'python -m pip install -e /root/py-tracer\n'
            'SITEPKG=$(python -c "import site;print(site.getsitepackages()[0])")\n'
            'echo \'import runpy; runpy.run_path("/root/py-tracer/tracer_plugin/sympy_plugin.py", run_name="__main__")\' > "${SITEPKG}/zzz_tracer_boot.pth"\n'
            'export ENABLE_TRACER=1\n'
            f'export TRACER_OUTPUT_DIR=/{mode}_traces\n'
        )
    else:
        return (
            'source /opt/miniconda3/bin/activate\n'
            'conda activate testbed\n'
            'python -m pip install -e /root/py-tracer\n'
            f'export PYTEST_ADDOPTS="-p tracer_plugin --output=/{mode}_traces"'
        )

def update_eval_script(instance_id: str, eval_script: str, mode: str):
    lines = eval_script.splitlines()
    # Insert before the test runner call
    idx = lines.index(": '>>>>> Start Test Output'")
    lines.insert(idx, get_injected_script(instance_id, mode))
    return "\n".join(lines)

def run_buggy_code(container, instance_id, test_spec, logger, log_dir, timeout):
    eval_file = Path(log_dir / "eval.sh")
    eval_file.write_text(update_eval_script(instance_id, test_spec.eval_script, "buggy"))
    logger.info(
        f"Eval script for {instance_id} written to {eval_file}; copying to container..."
    )
    copy_to_container(container, eval_file, PurePosixPath("/eval.sh"))
    test_output, timed_out, total_runtime = exec_run_with_timeout(
        container, "/bin/bash /eval.sh", timeout
    )
    copy_directory_from_docker(container, PurePosixPath(f"/buggy_traces"), log_dir)
    test_output_path = log_dir / "test_output_buggy.txt"
    logger.info(f"Test runtime: {total_runtime:_.2f} seconds")
    with open(test_output_path, "w") as f:
        f.write(test_output)
        logger.info(f"Test output for {instance_id} written to {test_output_path}")
        if timed_out:
            f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
            raise EvaluationError(
                instance_id,
                f"Test timed out after {timeout} seconds.",
                logger,
            )

def run_patched_write_script(instance_id, eval_file, test_spec):
    eval_file.write_text(update_eval_script(instance_id, test_spec.eval_script, "patched"))

def run_patched_copy_out(container, log_dir):
    copy_directory_from_docker(container, PurePosixPath(f"/patched_traces"), log_dir)

def monkey_patch():
    # Install tracer and the pytest plugin
    when(run_instance, 156).do(install_tracer)
    # Run tests for buggy code with tracer
    when(run_instance, 159).do(run_buggy_code)
    # Run tests for patched code with tracer
    when(run_instance, 200).do(run_patched_write_script)
    when(run_instance, 209).do(run_patched_copy_out)
    when(run_instance, 211).do('test_output_path = log_dir / "test_output_patched.txt"')
    print('Monkey patch applied')
