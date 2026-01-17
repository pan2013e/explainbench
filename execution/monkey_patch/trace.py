import os
import json
from pathlib import Path, PurePosixPath

from dowhen import when
from swebench.harness.run_evaluation import (
    run_instance,
    main,
)
from swebench.harness.docker_utils import (
    copy_to_container,
    exec_run_with_timeout
)
from swebench.harness.utils import EvaluationError

from execution.util import (
    copy_directory_from_docker,
    get_fail_to_pass_tests,
    get_tmp_tracer_path,
)

DIR = os.path.dirname(os.path.abspath(__file__))
GLOBAL_ARGS = dict()

def get_allowed_functions(agent, instance_id):
    dataset_file = "/home/yusuf/explainbench/shared_logs/rq3/allowed_functions_all.json"
    if not os.path.exists(dataset_file):
        print(f"Warning: Allowed functions dataset file not found at {dataset_file}")
        return 'none'
    with open(dataset_file, 'r') as f:
        data = json.load(f)
    allowed_functions_agent = data.get(agent, {})
    if not allowed_functions_agent:
        print(f"Warning: No allowed functions found for {agent}")
        return 'none'
    allowed_functions = allowed_functions_agent.get(instance_id, [])
    if not allowed_functions:
        print(f"Warning: No allowed functions found for ({agent}, {instance_id})")
        return 'none'
    return ','.join(allowed_functions)

def get_pytest_addopts(instance_id, mode):
    return f'--output=/{mode}_traces --allowed-functions="{get_allowed_functions(GLOBAL_ARGS["agent"], instance_id)}"'

def get_pth_addenv(instance_id, mode):
    return (
        f'export TRACER_OUTPUT_DIR=/{mode}_traces\n'
        f'export TRACER_ALLOWED_FUNCTIONS="{get_allowed_functions(GLOBAL_ARGS["agent"], instance_id)}"'
    )

def install_tracer(container, logger):
    with open(get_tmp_tracer_path(), 'rb') as f:
        container.put_archive('/root', f)
    logger.info("Tracer code copied to container")

def get_injected_script(instance_id: str, mode: str):
    if 'django' in instance_id or 'sympy' in instance_id:
        project = 'django' if 'django' in instance_id else 'sympy'
        return (
            'source /opt/miniconda3/bin/activate\n'
            'conda activate testbed\n'
            'python -m pip install /root/py-tracer\n'
            'SITEPKG=$(python -c "import site;print(site.getsitepackages()[0])")\n'
            f'echo \'import os; _path = "/root/py-tracer/tracer_plugin/{project}_plugin.py"; code = open(_path).read(); code = compile(code, _path, "exec"); exec(code, {{"__name__": "__main__"}})\' > "${{SITEPKG}}/zzz_tracer_boot.pth"\n'
            'export ENABLE_TRACER=1\n'
            f'export INSTANCE_ID={instance_id}\n'
            f'{get_pth_addenv(instance_id, mode)}\n'
            'export PYTHONHASHSEED=42'
        )
    else:
        return (
            'source /opt/miniconda3/bin/activate\n'
            'conda activate testbed\n'
            'python -m pip install /root/py-tracer\n'
            'export PYTHONHASHSEED=42'
        )

def get_hijacked_test_runner_call(instance_id: str, mode: str, orig_line: str):
    fail_to_pass_tests = get_fail_to_pass_tests(instance_id)
    fail_to_pass_tests = [f'"{test}"' for test in fail_to_pass_tests]
    if 'django' in instance_id:
        return None
    elif 'sympy' in instance_id:
        return orig_line.replace(" -C ", f' -k {" ".join(fail_to_pass_tests)} --seed 7357232 ')
    elif 'sphinx' in instance_id:
        prefix = orig_line.split(' -- ')[0].strip()
        return f'{prefix} -- {" ".join(fail_to_pass_tests)} {get_pytest_addopts(instance_id, mode)}'
    else:
        return f'pytest -rA {" ".join(fail_to_pass_tests)} {get_pytest_addopts(instance_id, mode)}'

def update_eval_script(instance_id: str, eval_script: str, mode: str):
    lines = eval_script.splitlines()
    # Insert before the test runner call
    idx = lines.index(": '>>>>> Start Test Output'")
    # Replace the test runner call to only run the fail-to-pass tests
    subset_call = get_hijacked_test_runner_call(instance_id, mode, lines[idx + 1])
    if subset_call is not None:
        lines[idx + 1] = subset_call
    # Inject tracer setup script
    lines.insert(idx, get_injected_script(instance_id, mode))
    # For patched code testing, no need to install repo dependencies again
    if mode == "patched":
        install_line_idx = -1
        for idx, line in enumerate(lines):
            if line.startswith("python -m pip install") or line.startswith("python setup.py install"):
                install_line_idx = idx
                break
        assert install_line_idx != -1, "Install line not found in eval script"
        lines[install_line_idx] = "# " + lines[install_line_idx]
    lines.append("git clean -fd")
    lines.append("rm -rf /tmp/*")
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

def monkey_patch_execution(**kwargs):
    GLOBAL_ARGS.update(kwargs)
    # Skip docker communication after evaluation
    when(main, 569).do("client = None")
    # Install tracer and the pytest plugin
    when(run_instance, 156).do(install_tracer)
    # Run tests for buggy code with tracer
    when(run_instance, 159).do(run_buggy_code)
    # Run tests for patched code with tracer
    when(run_instance, 200).do(run_patched_write_script)
    when(run_instance, 209).do(run_patched_copy_out)
    when(run_instance, 211).do('test_output_path = log_dir / "test_output_patched.txt"')
    print('Monkey patch applied to run_instance and main in swebench.harness.run_evaluation')
