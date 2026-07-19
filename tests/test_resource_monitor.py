import json
import sys

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest


REPOSITORY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from execution.resource_monitor import (
    ContainerAggregate,
    CpuCounters,
    FilesystemReading,
    HostResourceSampler,
    HostSample,
    RunCompletion,
    RunResourceConfig,
    RunResourceMonitor,
    SampleResult,
    _parse_meminfo,
    _parse_proc_stat,
)
import execution.resource_monitor as resource_monitor


UTC = timezone.utc
SOFTWARE_METADATA = {
    "explainbench_git_revision": "abc123",
    "explainbench_git_dirty": False,
    "python_version": "3.12.0",
    "swebench_version": "4.1.0",
    "docker_sdk_version": "7.1.0",
}
HOST_METADATA = {
    "operating_system": "Test Linux",
    "kernel_version": "1.0.0",
    "architecture": "x86_64",
    "cpu_model": "Test CPU",
    "logical_cpu_count": 8,
    "memory_total_bytes": 1_000,
    "swap_total_bytes": 100,
    "storage_type": None,
    "docker_server_version": "28.0.1",
    "docker_api_version": "1.48",
    "docker_storage_driver": "overlay2",
    "docker_data_root": "/docker",
    "cgroup_version": "1",
}
DOCKER_METADATA = {
    "server_version": "28.0.1",
    "api_version": "1.48",
    "storage_driver": "overlay2",
    "data_root": "/docker",
    "cgroup_version": "1",
}


class SequenceSampleSource:
    filesystem_paths = {
        "trace_output": "/trace",
        "docker_data_root": "/docker",
    }

    def __init__(self, samples):
        self.samples = list(samples)
        self.index = 0

    def collect(self):
        index = min(self.index, len(self.samples) - 1)
        self.index += 1
        return SampleResult(self.samples[index])


class FailingSampleSource:
    filesystem_paths = {
        "trace_output": "/trace",
        "docker_data_root": "/docker",
    }

    def collect(self):
        raise OSError("host metrics unavailable")


def make_sample(
    offset,
    *,
    cpu_total,
    cpu_idle,
    memory_available,
    swap_free,
    load1,
    trace_available,
    docker_available,
    active_containers,
    aggregate_working_set,
):
    return HostSample(
        observed_at=datetime(2026, 7, 18, tzinfo=UTC) + timedelta(seconds=offset),
        monotonic_ns=offset * 1_000_000_000,
        cpu=CpuCounters(total=cpu_total, idle=cpu_idle),
        memory_total_bytes=1_000,
        memory_available_bytes=memory_available,
        swap_total_bytes=100,
        swap_free_bytes=swap_free,
        load1=load1,
        filesystems={
            "trace_output": FilesystemReading(10_000, trace_available),
            "docker_data_root": FilesystemReading(20_000, docker_available),
        },
        containers=ContainerAggregate(active_containers, aggregate_working_set),
    )


def sample_pair():
    return [
        make_sample(
            1,
            cpu_total=100,
            cpu_idle=40,
            memory_available=600,
            swap_free=100,
            load1=1.0,
            trace_available=8_000,
            docker_available=16_000,
            active_containers=1,
            aggregate_working_set=100,
        ),
        make_sample(
            2,
            cpu_total=200,
            cpu_idle=60,
            memory_available=500,
            swap_free=90,
            load1=2.0,
            trace_available=7_500,
            docker_available=15_000,
            active_containers=2,
            aggregate_working_set=250,
        ),
    ]


def make_monitor(tmp_path, source, output_name="resource_usage.run.json"):
    return RunResourceMonitor(
        RunResourceConfig(
            run_id="trace.gold.1000",
            agent="gold",
            instance_selection=["django"],
            resolved_instance_ids=["django__django-1", "django__django-2"],
            max_workers=2,
            timeout_seconds=21_600,
            cache_state="warm",
        ),
        tmp_path / output_name,
        tmp_path,
        interval_seconds=60,
        sample_source=source,
        software_metadata=SOFTWARE_METADATA,
        host_metadata=HOST_METADATA,
        docker_metadata=DOCKER_METADATA,
    )


def test_proc_parsers_use_capacity_semantics():
    cpu = _parse_proc_stat("cpu  10 2 3 40 5 1 2 4 0 0\ncpu0 1 0 0 1")
    memory = _parse_meminfo(
        "MemTotal: 1000 kB\n"
        "MemAvailable: 400 kB\n"
        "SwapTotal: 200 kB\n"
        "SwapFree: 150 kB\n"
    )

    assert cpu == CpuCounters(total=67, idle=45)
    assert memory == {
        "MemTotal": 1_024_000,
        "MemAvailable": 409_600,
        "SwapTotal": 204_800,
        "SwapFree": 153_600,
    }


def test_sampler_aggregates_host_peaks_and_cpu_percent():
    sampler = HostResourceSampler(
        SequenceSampleSource(sample_pair()), interval_seconds=60
    )

    sampler.start()
    sampler.stop()
    snapshot = sampler.snapshot()

    assert snapshot["sampling"]["attempted_samples"] == 2
    assert snapshot["sampling"]["successful_samples"] == 2
    assert snapshot["metrics"] == {
        "memory_used_sampled_peak_bytes": 500,
        "memory_available_sampled_min_bytes": 500,
        "swap_used_sampled_peak_bytes": 10,
        "cpu_percent_mean": 80.0,
        "cpu_percent_peak": 80.0,
        "load1_sampled_peak": 2.0,
        "active_trace_containers_peak": 2,
        "aggregate_container_working_set_sampled_peak_bytes": 250,
    }
    filesystems = {entry["role"]: entry for entry in snapshot["filesystems"]}
    assert filesystems["trace_output"]["available_start_bytes"] == 8_000
    assert filesystems["trace_output"]["available_min_bytes"] == 7_500
    assert filesystems["docker_data_root"]["available_min_bytes"] == 15_000


def test_monitor_record_matches_resource_schema(tmp_path):
    monitor = make_monitor(tmp_path, SequenceSampleSource(sample_pair()))
    record = monitor.start().stop(
        RunCompletion(
            instances_completed=2,
            trace_artifact_total_bytes=1_024,
        )
    )

    schema_path = REPOSITORY_ROOT / "execution" / "resource_usage.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(record)

    assert record["measurement"] == {"state": "complete", "missing_metrics": []}
    assert record["summary"]["instances_completed"] == 2
    assert record["summary"]["trace_artifact_total_bytes"] == 1_024
    assert not list(tmp_path.glob(".*.tmp"))


def test_context_interrupt_flushes_an_interrupted_record(tmp_path):
    monitor = make_monitor(tmp_path, SequenceSampleSource(sample_pair()))

    with pytest.raises(KeyboardInterrupt):
        with monitor:
            raise KeyboardInterrupt

    record = json.loads(
        (tmp_path / "resource_usage.run.json").read_text(encoding="utf-8")
    )
    assert record["run"]["state"] == "interrupted"
    assert record["run"]["ended_at"] is not None
    assert record["sampling"]["successful_samples"] == 2


def test_unavailable_source_still_writes_failure_evidence(tmp_path):
    monitor = make_monitor(tmp_path, FailingSampleSource())

    record = monitor.start().stop(RunCompletion(state="failed"))

    assert record["run"]["state"] == "failed"
    assert record["measurement"]["state"] == "unavailable"
    assert record["sampling"]["attempted_samples"] == 2
    assert record["sampling"]["failed_samples"] == 2
    assert record["errors"] == [
        {
            "source": "measurement",
            "code": "host_sample_failed",
            "message": "host.sample: host metrics unavailable",
            "exception_type": "OSError",
        }
    ]


def test_atomic_write_replaces_an_existing_partial_record(tmp_path):
    output_path = tmp_path / "resource_usage.run.json"
    output_path.write_text('{"incomplete": true', encoding="utf-8")
    monitor = make_monitor(
        tmp_path,
        SequenceSampleSource(sample_pair()),
    )

    record = monitor.start().stop(
        RunCompletion(instances_completed=2, trace_artifact_total_bytes=8)
    )

    assert json.loads(output_path.read_text(encoding="utf-8")) == record
    assert not list(tmp_path.glob(".resource_usage.run.json.*.tmp"))


def test_atomic_write_failure_preserves_previous_record(tmp_path, monkeypatch):
    output_path = tmp_path / "resource_usage.run.json"
    previous = '{"schema_version": 0, "state": "partial"}\n'
    output_path.write_text(previous, encoding="utf-8")

    def fail_replace(source, destination):
        raise PermissionError("replacement blocked for test")

    monkeypatch.setattr(resource_monitor.os, "replace", fail_replace)

    with pytest.raises(PermissionError, match="replacement blocked"):
        resource_monitor._atomic_write_json(
            output_path, {"schema_version": 1, "state": "complete"}
        )

    assert output_path.read_text(encoding="utf-8") == previous
    assert not list(tmp_path.glob(".resource_usage.run.json.*.tmp"))
