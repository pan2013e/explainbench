import os
import json
import threading

from contextlib import contextmanager
from dataclasses import dataclass, field
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
from execution.docker_resource_monitor import (
    ArtifactStats,
    INSTANCE_RESOURCE_FILENAME,
    InstanceOutcome,
    InstanceResourceConfig,
    InstanceResourceMonitor,
    PhaseHandle,
    collect_artifact_stats,
)
from execution.resource_monitor import ContainerAggregate, RunCompletion

DIR = os.path.dirname(os.path.abspath(__file__))
GLOBAL_ARGS = dict()
RESOURCE_MONITORS = dict()
RESOURCE_LOCK = threading.RLock()
RUN_OUTCOMES = {
    "completed": 0,
    "partial": 0,
    "failed": 0,
    "interrupted": 0,
    "timed_out": 0,
}
RUN_ARTIFACTS = {"total_bytes": 0, "complete": True}


@dataclass
class InstanceMonitorState:
    monitor: InstanceResourceMonitor
    log_dir: Path
    buggy_trace_copied: bool = False
    buggy_artifact: ArtifactStats = field(default_factory=ArtifactStats)
    patched_artifact: ArtifactStats = field(default_factory=ArtifactStats)
    collected_artifacts: set[str] = field(default_factory=set)
    failure_kind: str | None = None
    failed_phase: str | None = None
    errors: list[dict[str, str | None]] = field(default_factory=list)


def _log_resource_warning(logger, message):
    logger.warning(f"Resource monitoring: {message}")


def _state_for(container):
    if container is None:
        return None
    with RESOURCE_LOCK:
        return RESOURCE_MONITORS.get(str(container.id))


def _record_monitor_error(state, code, error, logger):
    state.errors.append(
        {
            "source": "measurement",
            "code": code,
            "message": str(error).replace("\n", " ")[:500],
            "exception_type": error.__class__.__name__,
        }
    )
    _log_resource_warning(logger, f"{code}: {error}")


def _start_instance_monitor(container, instance_id, run_id, log_dir, logger):
    if not GLOBAL_ARGS.get("resource_monitoring", True):
        return None
    try:
        monitor = InstanceResourceMonitor(
            InstanceResourceConfig(
                run_id=run_id,
                agent=GLOBAL_ARGS["agent"],
                instance_id=instance_id,
            ),
            container,
            Path(log_dir) / INSTANCE_RESOURCE_FILENAME,
            cgroup_version=GLOBAL_ARGS.get("cgroup_version", "unknown"),
            interval_seconds=GLOBAL_ARGS.get("resource_sample_interval", 1.0),
        )
        monitor.start()
        state = InstanceMonitorState(monitor=monitor, log_dir=Path(log_dir))
        with RESOURCE_LOCK:
            RESOURCE_MONITORS[str(container.id)] = state
        return state
    except Exception as error:
        _log_resource_warning(logger, f"could not start instance monitor: {error}")
        return None


def _begin_resource_phase(container, phase_name, logger):
    state = _state_for(container)
    if state is None:
        return False
    try:
        state.monitor.sampler.begin_phase(phase_name)
        return True
    except Exception as error:
        _record_monitor_error(state, "resource_phase_start_failed", error, logger)
        return False


def _end_resource_phase(container, phase_state, logger):
    state = _state_for(container)
    if state is None or state.monitor.sampler.active_phase() is None:
        return
    try:
        state.monitor.sampler.end_phase(phase_state)
    except Exception as error:
        _record_monitor_error(state, "resource_phase_end_failed", error, logger)


@contextmanager
def _resource_phase(container, phase_name, logger):
    started = _begin_resource_phase(container, phase_name, logger)
    handle = PhaseHandle()
    try:
        yield handle
    except (KeyboardInterrupt, SystemExit):
        handle.state = "interrupted"
        raise
    except TimeoutError:
        handle.mark_timed_out()
        raise
    except Exception:
        handle.mark_failed()
        raise
    finally:
        if started:
            _end_resource_phase(container, handle.state, logger)


def get_active_container_aggregate():
    with RESOURCE_LOCK:
        states = list(RESOURCE_MONITORS.values())
    working_sets = [
        state.monitor.sampler.current_working_set_bytes() for state in states
    ]
    if any(value is None for value in working_sets):
        return ContainerAggregate(len(states), None)
    return ContainerAggregate(len(states), sum(working_sets))


def get_run_completion(run_state=None):
    with RESOURCE_LOCK:
        counts = RUN_OUTCOMES.copy()
        artifact_total = (
            RUN_ARTIFACTS["total_bytes"]
            if RUN_ARTIFACTS["complete"]
            else None
        )
    if run_state is None:
        run_state = (
            "partial"
            if counts["partial"] or counts["failed"] or counts["interrupted"]
            else "completed"
        )
    return RunCompletion(
        state=run_state,
        instances_completed=counts["completed"],
        instances_partial=counts["partial"],
        instances_failed=counts["failed"],
        instances_interrupted=counts["interrupted"],
        instances_timed_out=counts["timed_out"],
        trace_artifact_total_bytes=artifact_total,
    )


def _collect_trace_artifact(state, mode, logger, *, copy_completed):
    try:
        artifact, errors = collect_artifact_stats(
            state.log_dir / f"{mode}_traces"
        )
        unexpected_state = (
            artifact.state == "complete" and not copy_completed
        ) or (artifact.state == "missing" and copy_completed)
        if unexpected_state:
            artifact = ArtifactStats(
                state="partial",
                file_count=artifact.file_count,
                total_bytes=artifact.total_bytes,
                largest_file_bytes=artifact.largest_file_bytes,
                event_count=artifact.event_count,
            )
            errors.append(
                {
                    "source": "measurement",
                    "code": "artifact_copy_incomplete",
                    "message": (
                        f"{mode} trace copy-out did not produce a complete "
                        "artifact directory"
                    ),
                    "exception_type": None,
                }
            )
        setattr(state, f"{mode}_artifact", artifact)
        state.collected_artifacts.add(mode)
        state.errors.extend(errors)
        for error in errors:
            _log_resource_warning(logger, f"{error['code']}: {error['message']}")
    except Exception as error:
        setattr(state, f"{mode}_artifact", ArtifactStats(state="partial"))
        state.collected_artifacts.add(mode)
        _record_monitor_error(
            state, "artifact_collection_failed", error, logger
        )

def get_allowed_functions(agent, instance_id):
    dataset_file = os.path.join(DIR, "../allowed_functions.json")
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

def install_tracer(container, logger, instance_id, run_id, log_dir):
    _start_instance_monitor(container, instance_id, run_id, log_dir, logger)
    with _resource_phase(container, "tracer_archive_copy", logger):
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
    with _resource_phase(container, "buggy_prepare", logger):
        eval_file = Path(log_dir / "eval.sh")
        eval_file.write_text(update_eval_script(instance_id, test_spec.eval_script, "buggy"))
        logger.info(
            f"Eval script for {instance_id} written to {eval_file}; copying to container..."
        )
        copy_to_container(container, eval_file, PurePosixPath("/eval.sh"))
    with _resource_phase(container, "buggy_exec", logger) as phase:
        test_output, timed_out, total_runtime = exec_run_with_timeout(
            container, "/bin/bash /eval.sh", timeout
        )
        if timed_out:
            phase.mark_timed_out()
    with _resource_phase(container, "buggy_copy_out", logger):
        copy_directory_from_docker(container, PurePosixPath(f"/buggy_traces"), log_dir)
    state = _state_for(container)
    if state is not None:
        state.buggy_trace_copied = True
        _collect_trace_artifact(state, "buggy", logger, copy_completed=True)
    test_output_path = log_dir / "test_output_buggy.txt"
    logger.info(f"Test runtime: {total_runtime:_.2f} seconds")
    with open(test_output_path, "w") as f:
        f.write(test_output)
        logger.info(f"Test output for {instance_id} written to {test_output_path}")
        if timed_out:
            if state is not None:
                state.failure_kind = "timeout"
                state.failed_phase = "buggy_exec"
            f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
            raise EvaluationError(
                instance_id,
                f"Test timed out after {timeout} seconds.",
                logger,
            )
    _begin_resource_phase(container, "patch_prepare_apply", logger)


def start_patched_prepare(container, logger):
    _end_resource_phase(container, "completed", logger)
    _begin_resource_phase(container, "patched_prepare", logger)

def run_patched_write_script(instance_id, eval_file, test_spec):
    eval_file.write_text(update_eval_script(instance_id, test_spec.eval_script, "patched"))


def start_patched_exec(container, logger):
    state = _state_for(container)
    if (
        state is not None
        and state.monitor.sampler.active_phase() == "patched_exec"
    ):
        return
    _end_resource_phase(container, "completed", logger)
    _begin_resource_phase(container, "patched_exec", logger)


def run_patched_copy_out(container, log_dir, timed_out, logger):
    _end_resource_phase(container, "timed_out" if timed_out else "completed", logger)
    state = _state_for(container)
    if timed_out and state is not None:
        state.failure_kind = "timeout"
        state.failed_phase = "patched_exec"
    with _resource_phase(container, "patched_copy_out", logger):
        copy_directory_from_docker(container, PurePosixPath(f"/patched_traces"), log_dir)
    if state is not None:
        _collect_trace_artifact(state, "patched", logger, copy_completed=True)


def start_grading(container, logger):
    _begin_resource_phase(container, "grading", logger)


def finalize_resource_monitor(_frame):
    local = _frame.f_locals
    container = local.get("container")
    logger = local.get("logger")
    state = _state_for(container)
    if state is None:
        if GLOBAL_ARGS.get("resource_monitoring", True):
            with RESOURCE_LOCK:
                RUN_OUTCOMES[
                    "completed" if local.get("eval_completed", False) else "failed"
                ] += 1
                RUN_ARTIFACTS["complete"] = False
        return

    eval_completed = bool(local.get("eval_completed", False))
    report = local.get("report", {})
    instance_id = local.get("instance_id")
    applied_patch = local.get("applied_patch")
    if not eval_completed and applied_patch is False and state.failure_kind is None:
        state.failure_kind = "patch_error"
        state.failed_phase = "patch_prepare_apply"

    active_phase = state.monitor.sampler.active_phase()
    if (
        not eval_completed
        and active_phase == "grading"
        and state.failure_kind is None
    ):
        state.failure_kind = "evaluation_error"
        state.failed_phase = "grading"
    if active_phase is not None:
        phase_state = "completed" if eval_completed else "failed"
        if state.failure_kind == "timeout" and active_phase == state.failed_phase:
            phase_state = "timed_out"
        _end_resource_phase(container, phase_state, logger)

    for mode in ("buggy", "patched"):
        if mode not in state.collected_artifacts:
            _collect_trace_artifact(
                state, mode, logger, copy_completed=False
            )

    if eval_completed:
        outcome = InstanceOutcome(
            state="completed",
            evaluation_completed=True,
            resolved=bool(report.get(instance_id, {}).get("resolved", False)),
        )
    else:
        outcome = InstanceOutcome(
            state="partial" if state.buggy_trace_copied else "failed",
            failure_kind=state.failure_kind or "unknown_error",
            failed_phase=state.failed_phase or active_phase,
            evaluation_completed=False,
            resolved=None,
        )

    try:
        record = state.monitor.stop(
            outcome,
            buggy_artifact=state.buggy_artifact,
            patched_artifact=state.patched_artifact,
            workload_errors=state.errors,
        )
        recorded_state = record["outcome"]["state"]
        with RESOURCE_LOCK:
            RUN_OUTCOMES[recorded_state] += 1
            if record["outcome"]["failure_kind"] == "timeout":
                RUN_OUTCOMES["timed_out"] += 1
            artifacts = record["artifacts"]
            RUN_ARTIFACTS["total_bytes"] += sum(
                artifact["total_bytes"] for artifact in artifacts.values()
            )
            if any(
                artifact["state"] == "partial"
                for artifact in artifacts.values()
            ):
                RUN_ARTIFACTS["complete"] = False
    except Exception as error:
        _log_resource_warning(logger, f"could not finalize instance monitor: {error}")
        with RESOURCE_LOCK:
            RUN_OUTCOMES["failed"] += 1
            RUN_ARTIFACTS["complete"] = False
    finally:
        with RESOURCE_LOCK:
            RESOURCE_MONITORS.pop(str(container.id), None)

def monkey_patch_execution(**kwargs):
    GLOBAL_ARGS.update(kwargs)
    with RESOURCE_LOCK:
        RESOURCE_MONITORS.clear()
        for key in RUN_OUTCOMES:
            RUN_OUTCOMES[key] = 0
        RUN_ARTIFACTS.update(total_bytes=0, complete=True)
    # Skip docker communication after evaluation
    when(main, 569).do("client = None")
    # Install tracer and the pytest plugin
    when(run_instance, 156).do(install_tracer)
    # Run tests for buggy code with tracer
    when(run_instance, 159).do(run_buggy_code)
    # Run tests for patched code with tracer
    when(run_instance, 'eval_file = Path(log_dir / "eval.sh")').do(start_patched_prepare)
    when(run_instance, 200).do(run_patched_write_script)
    when(run_instance, "test_output, timed_out, total_runtime = exec_run_with_timeout(").do(start_patched_exec)
    when(run_instance, 209).do(run_patched_copy_out)
    when(run_instance, 211).do('test_output_path = log_dir / "test_output_patched.txt"')
    when(run_instance, "git_diff_output_after = (").do(start_grading)
    # Finalize resource metrics before the container is removed
    when(run_instance, "cleanup_container(client, container, logger)").do(finalize_resource_monitor)
    print('Monkey patch applied to run_instance and main in swebench.harness.run_evaluation')
