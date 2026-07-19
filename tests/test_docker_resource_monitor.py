import json
import sys

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest


REPOSITORY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

import execution.docker_resource_monitor as docker_resource_monitor
from execution.docker_resource_monitor import (
    ArtifactStats,
    DockerContainerSampleSource,
    DockerContainerSampler,
    DockerRunAggregateProvider,
    DockerSampleResult,
    DockerStatsSnapshot,
    InstanceOutcome,
    InstanceResourceConfig,
    InstanceResourceMonitor,
    collect_artifact_stats,
    parse_docker_stats,
)


UTC = timezone.utc


def raw_stats(
    *,
    cpu=100,
    system_cpu=1_000,
    memory=1_000,
    inactive=100,
    max_memory=1_200,
    read=10,
    write=20,
    pids=3,
):
    return {
        "cpu_stats": {
            "cpu_usage": {"total_usage": cpu, "percpu_usage": [1, 1, 1, 1]},
            "system_cpu_usage": system_cpu,
        },
        "memory_stats": {
            "usage": memory,
            "max_usage": max_memory,
            "stats": {
                "inactive_file": inactive,
                "total_inactive_file": inactive,
            },
        },
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"major": 8, "minor": 0, "op": "Read", "value": read},
                {"major": 8, "minor": 0, "op": "Write", "value": write},
                {"major": 8, "minor": 0, "op": "Total", "value": read + write},
                {"major": 8, "minor": 0, "op": "Sync", "value": write},
            ]
        },
        "pids_stats": {"current": pids},
    }


def snapshot(offset, *, cpu, system_cpu, memory, read, write, pids):
    return DockerStatsSnapshot(
        observed_at=datetime(2026, 7, 18, tzinfo=UTC)
        + timedelta(seconds=offset),
        monotonic_ns=offset * 1_000_000_000,
        container_id="container-1",
        cpu_total_usage_ns=cpu,
        system_cpu_usage_ns=system_cpu,
        online_cpus=4,
        memory_usage_bytes=memory,
        memory_working_set_bytes=memory - 100,
        docker_max_usage_bytes=memory + 50,
        block_io_read_bytes=read,
        block_io_write_bytes=write,
        pids_current=pids,
    )


def snapshot_sequence():
    return [
        snapshot(1, cpu=100, system_cpu=1_000, memory=1_000, read=10, write=20, pids=3),
        snapshot(2, cpu=200, system_cpu=2_000, memory=1_100, read=20, write=40, pids=4),
        snapshot(3, cpu=300, system_cpu=3_000, memory=1_300, read=30, write=70, pids=5),
        snapshot(4, cpu=400, system_cpu=4_000, memory=1_200, read=40, write=90, pids=4),
        snapshot(5, cpu=500, system_cpu=5_000, memory=1_100, read=50, write=100, pids=3),
    ]


class SequenceDockerSource:
    container_id = "container-1"

    def __init__(self, snapshots, fail_after=None):
        self.snapshots = list(snapshots)
        self.fail_after = fail_after
        self.index = 0

    def collect(self):
        if self.fail_after is not None and self.index >= self.fail_after:
            self.index += 1
            raise RuntimeError("container disappeared")
        index = min(self.index, len(self.snapshots) - 1)
        self.index += 1
        return DockerSampleResult(self.snapshots[index])

    def inspect_container(self):
        return (
            {
                "id": self.container_id,
                "image": "example:latest",
                "memory_limit_bytes": None,
                "nano_cpus": None,
                "pids_limit": None,
            },
            [],
        )

    def read_cgroup_v2_memory_peak(self):
        return None, None

    def read_oom_killed(self):
        return False, None


class ExecResult:
    def __init__(self, output, exit_code=0):
        self.output = output
        self.exit_code = exit_code


class FakeApi:
    _version = "1.48"


class FakeContainerClient:
    api = FakeApi()


class InspectableContainer:
    id = "container-1"
    client = FakeContainerClient()

    def __init__(self):
        self.stats_kwargs = None
        self.attrs = {
            "Config": {"Image": "example:latest"},
            "HostConfig": {
                "Memory": 8_000,
                "NanoCpus": 2_000_000_000,
                "PidsLimit": 100,
            },
            "State": {"OOMKilled": False},
        }

    def stats(self, **kwargs):
        self.stats_kwargs = kwargs
        return raw_stats()

    def reload(self):
        return None

    def exec_run(self, command, user=None):
        if command[-1].endswith("memory.peak"):
            return ExecResult(b"4096\n")
        return ExecResult(b"low 0\nhigh 0\nmax 0\noom 1\noom_kill 1\n")


class AggregateContainer:
    def __init__(self, name, stats):
        self.name = name
        self._stats = stats

    def stats(self, **kwargs):
        return self._stats


class ContainerCollection:
    def __init__(self, containers):
        self._containers = containers
        self.filters = None

    def list(self, filters):
        self.filters = filters
        return self._containers


class AggregateClient:
    def __init__(self, containers):
        self.containers = ContainerCollection(containers)


def make_monitor(tmp_path, source):
    return InstanceResourceMonitor(
        InstanceResourceConfig(
            run_id="trace.gold.1000",
            agent="gold",
            instance_id="django__django-1",
        ),
        container=None,
        output_path=tmp_path / "resource_usage.json",
        interval_seconds=60,
        sample_source=source,
    )


def test_parse_docker_stats_uses_cgroup_v1_working_set_and_exact_io_ops():
    parsed = parse_docker_stats(
        raw_stats(),
        container_id="container-1",
        cgroup_version="1",
        observed_at=datetime(2026, 7, 18, tzinfo=UTC),
        monotonic_ns=1,
    )

    assert parsed.online_cpus == 4
    assert parsed.memory_usage_bytes == 1_000
    assert parsed.memory_working_set_bytes == 900
    assert parsed.docker_max_usage_bytes == 1_200
    assert parsed.block_io_read_bytes == 10
    assert parsed.block_io_write_bytes == 20
    assert parsed.pids_current == 3


def test_parse_missing_docker_fields_remains_explicitly_unavailable(tmp_path):
    parsed = parse_docker_stats(
        {},
        container_id="container-1",
        cgroup_version="1",
        observed_at=datetime(2026, 7, 18, tzinfo=UTC),
        monotonic_ns=1,
    )
    monitor = make_monitor(tmp_path, SequenceDockerSource([parsed]))

    record = monitor.start().stop(
        InstanceOutcome(state="failed", failure_kind="docker_error"),
        buggy_artifact=ArtifactStats(state="complete"),
        patched_artifact=ArtifactStats(state="complete"),
    )

    assert parsed.cpu_total_usage_ns is None
    assert parsed.memory_usage_bytes is None
    assert parsed.memory_working_set_bytes is None
    assert parsed.block_io_read_bytes is None
    assert parsed.block_io_write_bytes is None
    assert parsed.pids_current is None
    assert record["measurement"]["state"] == "partial"
    assert record["measurement"]["missing_metrics"] == [
        "container.block_io_read_bytes",
        "container.block_io_write_bytes",
        "container.cpu_usage_ns",
        "container.memory_usage_bytes",
        "container.memory_working_set_bytes",
        "container.pids_current",
    ]


def test_container_source_reads_limits_cgroup_peak_and_oom_evidence():
    container = InspectableContainer()
    source = DockerContainerSampleSource(container, cgroup_version="2")

    result = source.collect()
    metadata, errors = source.inspect_container()
    peak, peak_error = source.read_cgroup_v2_memory_peak()
    oom_killed, oom_error = source.read_oom_killed()

    assert result.snapshot.memory_working_set_bytes == 900
    assert result.snapshot.docker_max_usage_bytes is None
    assert container.stats_kwargs == {"stream": False, "one_shot": True}
    assert metadata["memory_limit_bytes"] == 8_000
    assert metadata["nano_cpus"] == 2_000_000_000
    assert metadata["pids_limit"] == 100
    assert errors == []
    assert (peak, peak_error) == (4_096, None)
    assert (oom_killed, oom_error) == (True, None)


def test_sampler_attributes_counter_deltas_and_peaks_to_phase():
    sampler = DockerContainerSampler(
        SequenceDockerSource(snapshot_sequence()), interval_seconds=60
    )

    sampler.start()
    with sampler.phase("buggy_exec"):
        pass
    sampler.stop()
    record = sampler.snapshot()

    phase = record["phases"]["buggy_exec"]
    assert phase["state"] == "completed"
    assert phase["metrics"]["cpu_usage_ns"] == 100
    assert phase["metrics"]["cpu_percent_mean"] == 40.0
    assert phase["metrics"]["memory_usage_sampled_peak_bytes"] == 1_300
    assert phase["metrics"]["memory_working_set_sampled_peak_bytes"] == 1_200
    assert phase["metrics"]["block_io_read_bytes"] == 10
    assert phase["metrics"]["block_io_write_bytes"] == 30
    assert phase["metrics"]["pids_sampled_peak"] == 5
    assert record["container_metrics"]["cpu_usage_ns"] == 300
    assert record["sampling"]["successful_samples"] == 4
    assert not sampler._thread.is_alive()


def test_phase_context_records_timeout_before_propagating():
    sampler = DockerContainerSampler(
        SequenceDockerSource(snapshot_sequence()), interval_seconds=60
    )
    sampler.start()

    with pytest.raises(TimeoutError):
        with sampler.phase("patched_exec"):
            raise TimeoutError("test timeout")
    sampler.stop()

    assert sampler.snapshot()["phases"]["patched_exec"]["state"] == "timed_out"


def test_instance_monitor_writes_schema_valid_record(tmp_path):
    monitor = make_monitor(tmp_path, SequenceDockerSource(snapshot_sequence()))
    monitor.start()
    with monitor.sampler.phase("buggy_exec"):
        pass
    record = monitor.stop(
        InstanceOutcome(
            state="completed",
            evaluation_completed=True,
            resolved=True,
        ),
        buggy_artifact=ArtifactStats(
            state="complete", file_count=1, total_bytes=100, largest_file_bytes=100
        ),
        patched_artifact=ArtifactStats(
            state="complete", file_count=1, total_bytes=120, largest_file_bytes=120
        ),
    )

    schema = json.loads(
        (REPOSITORY_ROOT / "execution" / "resource_usage.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(record)

    assert record["measurement"] == {"state": "complete", "missing_metrics": []}
    assert record["container"]["lifetime_peak_memory_source"] == "docker_max_usage"
    assert record["container"]["lifetime_peak_memory_bytes"] == 1_350
    assert json.loads(
        (tmp_path / "resource_usage.json").read_text(encoding="utf-8")
    ) == record
    assert not list(tmp_path.glob(".*.tmp"))


def test_collect_artifact_stats_uses_recursive_file_metadata(tmp_path):
    artifact_dir = tmp_path / "buggy_traces"
    nested_dir = artifact_dir / "nested"
    nested_dir.mkdir(parents=True)
    (artifact_dir / "first.jsonl").write_bytes(b"123")
    (nested_dir / "second.jsonl").write_bytes(b"12345")
    (artifact_dir / "ignored-link").symlink_to(nested_dir / "second.jsonl")

    stats, errors = collect_artifact_stats(artifact_dir)

    assert stats == ArtifactStats(
        state="complete",
        file_count=2,
        total_bytes=8,
        largest_file_bytes=5,
    )
    assert errors == []


def test_collect_artifact_stats_reports_missing_directory(tmp_path):
    stats, errors = collect_artifact_stats(tmp_path / "missing")

    assert stats == ArtifactStats()
    assert errors == []


def test_collect_artifact_stats_preserves_partial_results(
    tmp_path, monkeypatch
):
    artifact_dir = tmp_path / "patched_traces"
    blocked_dir = artifact_dir / "blocked"
    blocked_dir.mkdir(parents=True)
    (artifact_dir / "visible.jsonl").write_bytes(b"1234")
    original_scandir = docker_resource_monitor.os.scandir

    def controlled_scandir(path):
        if Path(path) == blocked_dir:
            raise PermissionError("blocked for test")
        return original_scandir(path)

    monkeypatch.setattr(
        docker_resource_monitor.os, "scandir", controlled_scandir
    )

    stats, errors = collect_artifact_stats(artifact_dir)

    assert stats == ArtifactStats(
        state="partial",
        file_count=1,
        total_bytes=4,
        largest_file_bytes=4,
    )
    assert [error["code"] for error in errors] == ["artifact_scan_failed"]
    assert errors[0]["exception_type"] == "PermissionError"


def test_instance_context_flushes_timeout_and_phase_evidence(tmp_path):
    monitor = make_monitor(tmp_path, SequenceDockerSource(snapshot_sequence()))

    with pytest.raises(TimeoutError):
        with monitor:
            with monitor.sampler.phase("patched_exec"):
                raise TimeoutError("patched execution timed out")

    record = json.loads(
        (tmp_path / "resource_usage.json").read_text(encoding="utf-8")
    )
    assert record["outcome"]["state"] == "partial"
    assert record["outcome"]["failure_kind"] == "timeout"
    assert record["phases"]["patched_exec"]["state"] == "timed_out"
    assert record["errors"][-1] == {
        "source": "workload",
        "code": "instance_monitor_context_error",
        "message": "patched execution timed out",
        "exception_type": "TimeoutError",
    }


def test_instance_context_flushes_system_exit_and_stops_active_phase(tmp_path):
    monitor = make_monitor(tmp_path, SequenceDockerSource(snapshot_sequence()))

    with pytest.raises(SystemExit):
        with monitor:
            monitor.sampler.begin_phase("buggy_exec")
            raise SystemExit(2)

    record = json.loads(
        (tmp_path / "resource_usage.json").read_text(encoding="utf-8")
    )
    assert record["outcome"]["state"] == "interrupted"
    assert record["outcome"]["failure_kind"] == "cancelled"
    assert record["phases"]["buggy_exec"]["state"] == "interrupted"
    assert not monitor.sampler._thread.is_alive()


def test_disappearing_container_writes_partial_measurement(tmp_path):
    monitor = make_monitor(
        tmp_path, SequenceDockerSource(snapshot_sequence(), fail_after=1)
    )

    record = monitor.start().stop(
        InstanceOutcome(state="failed", failure_kind="docker_error"),
        buggy_artifact=ArtifactStats(
            state="complete", file_count=1, total_bytes=10, largest_file_bytes=10
        ),
        patched_artifact=ArtifactStats(
            state="complete", file_count=1, total_bytes=10, largest_file_bytes=10
        ),
    )

    assert record["measurement"]["state"] == "partial"
    assert record["sampling"]["failed_samples"] == 1
    assert record["errors"][0]["code"] == "docker_stats_failed"


def test_run_aggregate_provider_filters_exact_run_and_sums_working_sets():
    run_id = "trace.gold.1000"
    client = AggregateClient(
        [
            AggregateContainer(
                f"sweb.eval.django-1.{run_id}",
                raw_stats(memory=1_000, inactive=100),
            ),
            AggregateContainer(
                f"sweb.eval.sympy-2.{run_id}",
                raw_stats(memory=2_000, inactive=500),
            ),
            AggregateContainer(
                f"sweb.eval.unrelated.{run_id}.other",
                raw_stats(memory=9_000, inactive=0),
            ),
        ]
    )
    provider = DockerRunAggregateProvider(client, run_id, cgroup_version="1")

    aggregate = provider()

    assert client.containers.filters == {"name": run_id}
    assert aggregate.active_count == 2
    assert aggregate.working_set_bytes == 2_400


def test_concurrent_instance_monitors_write_isolated_atomic_records(tmp_path):
    def run_monitor(index):
        output_path = tmp_path / f"instance-{index}" / "resource_usage.json"
        monitor = InstanceResourceMonitor(
            InstanceResourceConfig(
                run_id="trace.gold.1000",
                agent="gold",
                instance_id=f"django__django-{index}",
            ),
            container=None,
            output_path=output_path,
            interval_seconds=60,
            sample_source=SequenceDockerSource(snapshot_sequence()),
        )
        monitor.start().stop(
            InstanceOutcome(
                state="completed",
                evaluation_completed=True,
                resolved=True,
            ),
            buggy_artifact=ArtifactStats(
                state="complete",
                file_count=1,
                total_bytes=index,
                largest_file_bytes=index,
            ),
            patched_artifact=ArtifactStats(
                state="complete",
                file_count=1,
                total_bytes=index + 1,
                largest_file_bytes=index + 1,
            ),
        )
        return output_path

    with ThreadPoolExecutor(max_workers=4) as executor:
        output_paths = list(executor.map(run_monitor, range(1, 9)))

    for index, output_path in enumerate(output_paths, start=1):
        record = json.loads(output_path.read_text(encoding="utf-8"))
        assert record["instance_id"] == f"django__django-{index}"
        assert record["artifacts"]["buggy"]["total_bytes"] == index
        assert not list(output_path.parent.glob(".resource_usage.json.*.tmp"))
