import importlib
import importlib.util
import json
import sys
import types

from pathlib import Path

import jsonschema
import pytest


REPOSITORY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))


class FakeLogger:
    def __init__(self, log_file):
        self.log_file = log_file
        self.messages = []

    def info(self, message):
        self.messages.append(("info", str(message)))

    def warning(self, message):
        self.messages.append(("warning", str(message)))

    def error(self, message):
        self.messages.append(("error", str(message)))


class FakeApi:
    _version = "1.48"


class FakeContainerClient:
    api = FakeApi()


class FakeExecResult:
    def __init__(self, output=b"", exit_code=0):
        self.output = output
        self.exit_code = exit_code


class FakeContainer:
    id = "phase4-container"
    client = FakeContainerClient()

    def __init__(self):
        self.stats_count = 0
        self.attrs = {
            "Config": {"Image": "phase4:test"},
            "HostConfig": {"Memory": 0, "NanoCpus": 0, "PidsLimit": None},
            "State": {"OOMKilled": False},
        }
        self.started = False
        self.archive_copied = False

    def start(self):
        self.started = True

    def put_archive(self, path, data):
        assert path == "/root"
        assert data.read() == b"tracer archive"
        self.archive_copied = True

    def stats(self, **kwargs):
        self.stats_count += 1
        count = self.stats_count
        return {
            "cpu_stats": {
                "cpu_usage": {
                    "total_usage": count * 100,
                    "percpu_usage": [1, 1, 1, 1],
                },
                "system_cpu_usage": count * 1_000,
            },
            "memory_stats": {
                "usage": 1_000 + count,
                "max_usage": 1_200 + count,
                "stats": {
                    "inactive_file": 100,
                    "total_inactive_file": 100,
                },
            },
            "blkio_stats": {
                "io_service_bytes_recursive": [
                    {"op": "Read", "value": count * 10},
                    {"op": "Write", "value": count * 20},
                ]
            },
            "pids_stats": {"current": 3},
        }

    def reload(self):
        return None

    def exec_run(self, command, **kwargs):
        if isinstance(command, str) and command.startswith("git -c"):
            return FakeExecResult(b"diff")
        return FakeExecResult(b"ok")


class FakeTestSpec:
    instance_id = "pytest-dev__pytest-1"
    is_remote_image = True
    instance_image_key = "phase4:test"
    eval_script = (
        "python -m pip install .\n"
        ": '>>>>> Start Test Output'\n"
        "pytest original-test\n"
    )


def _load_trace_patch_with_stubbed_util():
    module_name = "execution.monkey_patch.trace"
    sys.modules.pop(module_name, None)
    original_util = sys.modules.pop("execution.util", None)
    stub_util = types.ModuleType("execution.util")
    stub_util.copy_directory_from_docker = lambda *args, **kwargs: None
    stub_util.get_fail_to_pass_tests = lambda instance_id: ["test_selected"]
    stub_util.get_tmp_tracer_path = lambda: "unused"
    sys.modules["execution.util"] = stub_util
    try:
        module = importlib.import_module(module_name)
    finally:
        sys.modules.pop("execution.util", None)
        if original_util is not None:
            sys.modules["execution.util"] = original_util
    return module


def _start_direct_instance_monitor(trace_patch, tmp_path):
    log_dir = tmp_path / "trace.gold.1000" / "gold" / FakeTestSpec.instance_id
    log_dir.mkdir(parents=True)
    logger = FakeLogger(log_dir / "run_instance.log")
    container = FakeContainer()
    trace_patch.GLOBAL_ARGS.update(
        agent="gold",
        resource_monitoring=True,
        resource_sample_interval=60.0,
        cgroup_version="1",
    )
    state = trace_patch._start_instance_monitor(
        container,
        FakeTestSpec.instance_id,
        "trace.gold.1000",
        log_dir,
        logger,
    )
    assert state is not None
    return container, logger, log_dir, state


def _finalize_direct_instance(
    trace_patch,
    container,
    logger,
    *,
    eval_completed=False,
    applied_patch=True,
    report=None,
):
    trace_patch.finalize_resource_monitor(
        types.SimpleNamespace(
            f_locals={
                "container": container,
                "logger": logger,
                "eval_completed": eval_completed,
                "report": report or {},
                "instance_id": FakeTestSpec.instance_id,
                "applied_patch": applied_patch,
            }
        )
    )


def test_pinned_run_instance_hooks_record_all_trace_phases_before_cleanup(
    tmp_path, monkeypatch
):
    import dowhen
    import swebench.harness.run_evaluation as run_evaluation

    trace_patch = _load_trace_patch_with_stubbed_util()
    tracer_archive = tmp_path / "tracer.tar"
    tracer_archive.write_bytes(b"tracer archive")
    container = FakeContainer()
    copied_trace_modes = []
    cleanup_observations = []

    monkeypatch.setattr(run_evaluation, "RUN_EVALUATION_LOG_DIR", tmp_path)
    monkeypatch.setattr(
        run_evaluation,
        "setup_logger",
        lambda instance_id, log_file: FakeLogger(log_file),
    )
    monkeypatch.setattr(run_evaluation, "close_logger", lambda logger: None)
    monkeypatch.setattr(
        run_evaluation,
        "build_container",
        lambda *args, **kwargs: container,
    )
    monkeypatch.setattr(run_evaluation, "copy_to_container", lambda *args: None)
    monkeypatch.setattr(
        run_evaluation,
        "exec_run_with_timeout",
        lambda *args: ("patched output", False, 0.02),
    )
    monkeypatch.setattr(
        run_evaluation,
        "get_eval_report",
        lambda **kwargs: {FakeTestSpec.instance_id: {"resolved": True}},
    )

    def fake_cleanup(client, cleaned_container, logger):
        resource_path = (
            tmp_path
            / "trace.gold.1000"
            / "gold"
            / FakeTestSpec.instance_id
            / "resource_usage.json"
        )
        cleanup_observations.append(
            (cleaned_container is container, resource_path.exists())
        )

    monkeypatch.setattr(run_evaluation, "cleanup_container", fake_cleanup)
    monkeypatch.setattr(run_evaluation, "remove_image", lambda *args: None)
    monkeypatch.setattr(
        trace_patch, "get_tmp_tracer_path", lambda: str(tracer_archive)
    )
    monkeypatch.setattr(
        trace_patch, "get_fail_to_pass_tests", lambda instance_id: ["test_selected"]
    )
    monkeypatch.setattr(trace_patch, "copy_to_container", lambda *args: None)
    monkeypatch.setattr(
        trace_patch,
        "exec_run_with_timeout",
        lambda *args: ("buggy output", False, 0.01),
    )

    def fake_copy_directory(container_arg, source, destination):
        copied_trace_modes.append(source.name)
        trace_dir = destination / source.name
        trace_dir.mkdir(parents=True, exist_ok=True)
        contents = b"abc" if source.name == "buggy_traces" else b"12345"
        (trace_dir / "trace.jsonl").write_bytes(contents)

    monkeypatch.setattr(
        trace_patch, "copy_directory_from_docker", fake_copy_directory
    )

    dowhen.clear_all()
    try:
        trace_patch.monkey_patch_execution(
            agent="gold",
            resource_monitoring=True,
            resource_sample_interval=60.0,
            cgroup_version="1",
        )
        result = run_evaluation.run_instance(
            FakeTestSpec(),
            {
                "model_name_or_path": "gold",
                "model_patch": "diff --git a/a b/a\n",
            },
            False,
            False,
            object(),
            "trace.gold.1000",
            60,
            False,
        )
    finally:
        dowhen.clear_all()

    resource_path = (
        tmp_path
        / "trace.gold.1000"
        / "gold"
        / FakeTestSpec.instance_id
        / "resource_usage.json"
    )
    record = json.loads(resource_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (REPOSITORY_ROOT / "execution" / "resource_usage.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(record)

    assert result == {"completed": True, "resolved": True}
    assert container.started is True
    assert container.archive_copied is True
    assert copied_trace_modes == ["buggy_traces", "patched_traces"]
    assert cleanup_observations == [(True, True)]
    assert record["outcome"] == {
        "state": "completed",
        "failure_kind": None,
        "failed_phase": None,
        "evaluation_completed": True,
        "resolved": True,
    }
    assert set(record["phases"]) == {
        "tracer_archive_copy",
        "buggy_prepare",
        "buggy_exec",
        "buggy_copy_out",
        "patch_prepare_apply",
        "patched_prepare",
        "patched_exec",
        "patched_copy_out",
        "grading",
    }
    assert all(
        phase["state"] == "completed" for phase in record["phases"].values()
    )
    assert record["measurement"] == {"state": "complete", "missing_metrics": []}
    assert record["errors"] == []
    assert record["artifacts"] == {
        "buggy": {
            "state": "complete",
            "file_count": 1,
            "total_bytes": 3,
            "largest_file_bytes": 3,
            "event_count": None,
        },
        "patched": {
            "state": "complete",
            "file_count": 1,
            "total_bytes": 5,
            "largest_file_bytes": 5,
            "event_count": None,
        },
    }
    assert trace_patch.get_active_container_aggregate().active_count == 0
    completion = trace_patch.get_run_completion()
    assert completion.instances_completed == 1
    assert completion.instances_failed == 0
    assert completion.trace_artifact_total_bytes == 8


def test_buggy_timeout_writes_partial_record_and_stops_monitor(
    tmp_path, monkeypatch
):
    trace_patch = _load_trace_patch_with_stubbed_util()
    container, logger, log_dir, _state = _start_direct_instance_monitor(
        trace_patch, tmp_path
    )
    monkeypatch.setattr(trace_patch, "copy_to_container", lambda *args: None)
    monkeypatch.setattr(
        trace_patch,
        "exec_run_with_timeout",
        lambda *args: ("buggy output", True, 60.0),
    )

    def copy_buggy_trace(container_arg, source, destination):
        trace_dir = destination / source.name
        trace_dir.mkdir(parents=True)
        (trace_dir / "partial.jsonl").write_bytes(b"buggy")

    monkeypatch.setattr(
        trace_patch, "copy_directory_from_docker", copy_buggy_trace
    )

    try:
        with pytest.raises(trace_patch.EvaluationError):
            trace_patch.run_buggy_code(
                container,
                FakeTestSpec.instance_id,
                FakeTestSpec(),
                logger,
                log_dir,
                60,
            )
    finally:
        _finalize_direct_instance(trace_patch, container, logger)

    record = json.loads(
        (log_dir / "resource_usage.json").read_text(encoding="utf-8")
    )
    assert record["outcome"]["state"] == "partial"
    assert record["outcome"]["failure_kind"] == "timeout"
    assert record["outcome"]["failed_phase"] == "buggy_exec"
    assert record["phases"]["buggy_exec"]["state"] == "timed_out"
    assert record["artifacts"]["buggy"]["total_bytes"] == 5
    assert record["artifacts"]["patched"]["state"] == "missing"
    assert trace_patch.get_active_container_aggregate().active_count == 0
    assert trace_patch.get_run_completion().instances_timed_out == 1


def test_patched_timeout_is_attributed_before_copy_out(tmp_path, monkeypatch):
    trace_patch = _load_trace_patch_with_stubbed_util()
    container, logger, log_dir, state = _start_direct_instance_monitor(
        trace_patch, tmp_path
    )
    buggy_dir = log_dir / "buggy_traces"
    buggy_dir.mkdir()
    (buggy_dir / "trace.jsonl").write_bytes(b"buggy")
    state.buggy_trace_copied = True
    trace_patch._collect_trace_artifact(
        state, "buggy", logger, copy_completed=True
    )
    trace_patch._begin_resource_phase(container, "patched_exec", logger)

    def copy_patched_trace(container_arg, source, destination):
        trace_dir = destination / source.name
        trace_dir.mkdir(parents=True)
        (trace_dir / "trace.jsonl").write_bytes(b"patched")

    monkeypatch.setattr(
        trace_patch, "copy_directory_from_docker", copy_patched_trace
    )

    try:
        trace_patch.run_patched_copy_out(container, log_dir, True, logger)
    finally:
        _finalize_direct_instance(trace_patch, container, logger)

    record = json.loads(
        (log_dir / "resource_usage.json").read_text(encoding="utf-8")
    )
    assert record["outcome"]["state"] == "partial"
    assert record["outcome"]["failure_kind"] == "timeout"
    assert record["outcome"]["failed_phase"] == "patched_exec"
    assert record["phases"]["patched_exec"]["state"] == "timed_out"
    assert record["phases"]["patched_copy_out"]["state"] == "completed"
    assert record["artifacts"]["patched"]["total_bytes"] == 7
    assert trace_patch.get_active_container_aggregate().active_count == 0


def test_patch_application_failure_is_classified_and_flushed(tmp_path):
    trace_patch = _load_trace_patch_with_stubbed_util()
    container, logger, log_dir, _state = _start_direct_instance_monitor(
        trace_patch, tmp_path
    )

    _finalize_direct_instance(
        trace_patch, container, logger, applied_patch=False
    )

    record = json.loads(
        (log_dir / "resource_usage.json").read_text(encoding="utf-8")
    )
    assert record["outcome"] == {
        "state": "failed",
        "failure_kind": "patch_error",
        "failed_phase": "patch_prepare_apply",
        "evaluation_completed": False,
        "resolved": None,
    }
    assert record["artifacts"]["buggy"]["state"] == "missing"
    assert record["artifacts"]["patched"]["state"] == "missing"
    assert trace_patch.get_active_container_aggregate().active_count == 0


def test_trace_entrypoint_wraps_evaluation_in_run_monitor(tmp_path, monkeypatch):
    calls = []
    fake_run_evaluation = types.ModuleType("swebench.harness.run_evaluation")
    fake_run_evaluation.main = lambda **kwargs: calls.append(("evaluation", kwargs)) or {
        "ok": True
    }
    fake_constants = types.ModuleType("swebench.harness.constants")
    fake_constants.RUN_EVALUATION_LOG_DIR = tmp_path
    fake_patch = types.ModuleType("execution.monkey_patch.trace")
    fake_patch.get_active_container_aggregate = lambda: None
    fake_patch.get_run_completion = lambda run_state=None: types.SimpleNamespace(
        state=run_state or "completed"
    )
    fake_patch.monkey_patch_execution = lambda **kwargs: calls.append(
        ("patch", kwargs)
    )
    fake_util = types.ModuleType("execution.util")
    fake_util.prepare_tracer = lambda: calls.append(("prepare", None))
    fake_util.get_instance_ids = lambda value: ["django__django-1"]
    fake_util.get_predictions_path = lambda agent: "gold"

    replacements = {
        "swebench.harness.run_evaluation": fake_run_evaluation,
        "swebench.harness.constants": fake_constants,
        "execution.monkey_patch.trace": fake_patch,
        "execution.util": fake_util,
    }
    originals = {name: sys.modules.get(name) for name in replacements}
    sys.modules.update(replacements)
    try:
        spec = importlib.util.spec_from_file_location(
            "phase4_trace_entrypoint", REPOSITORY_ROOT / "execution" / "trace.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    class FakeRunMonitor:
        def __init__(self, **kwargs):
            calls.append(("monitor_init", kwargs))

        def start(self):
            calls.append(("monitor_start", None))

        def stop(self, completion):
            calls.append(("monitor_stop", completion.state))

    monkeypatch.setattr(module, "RunResourceMonitor", FakeRunMonitor)
    monkeypatch.setattr(
        module,
        "collect_docker_metadata",
        lambda: (
            {
                "server_version": "test",
                "api_version": "1.48",
                "storage_driver": "overlay2",
                "data_root": str(tmp_path),
                "cgroup_version": "1",
            },
            [],
        ),
    )

    result = module.main(
        agent="gold",
        instance_ids=["django"],
        max_workers=2,
        resource_sample_interval=0.5,
        resource_cache_state="warm",
        disable_resource_monitoring=False,
    )

    assert result == {"ok": True}
    assert [name for name, _ in calls] == [
        "patch",
        "monitor_init",
        "monitor_start",
        "prepare",
        "evaluation",
        "monitor_stop",
    ]
    monitor_config = next(value["config"] for name, value in calls if name == "monitor_init")
    assert monitor_config.max_workers == 2
    assert monitor_config.cache_state == "warm"
    evaluation_kwargs = next(value for name, value in calls if name == "evaluation")
    assert evaluation_kwargs["instance_ids"] == ["django__django-1"]
    assert evaluation_kwargs["run_id"].startswith("trace.gold.")
