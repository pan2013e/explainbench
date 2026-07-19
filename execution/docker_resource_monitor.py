from __future__ import annotations

import contextlib
import os
import stat
import threading
import time

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from execution.resource_monitor import (
    DEFAULT_SAMPLE_INTERVAL_SECONDS,
    SCHEMA_VERSION,
    ContainerAggregate,
    _atomic_write_json,
    _bounded_message,
    _format_timestamp,
)


INSTANCE_RESOURCE_FILENAME = "resource_usage.json"
PHASE_NAMES = {
    "container_setup",
    "tracer_archive_copy",
    "patch_prepare_apply",
    "buggy_prepare",
    "buggy_exec",
    "buggy_copy_out",
    "patched_prepare",
    "patched_exec",
    "patched_copy_out",
    "grading",
    "cleanup",
}
PHASE_STATES = {"completed", "timed_out", "failed", "interrupted", "skipped"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _api_supports_one_shot(version: str | None) -> bool:
    if not version:
        return False
    try:
        major, minor, *_ = (int(part) for part in version.split("."))
    except ValueError:
        return False
    return (major, minor) >= (1, 41)


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _sum_block_io(entries: Any, operation: str) -> int | None:
    if entries is None:
        return None
    if not isinstance(entries, list):
        return None
    total = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("op", "")).lower() != operation:
            continue
        value = _optional_nonnegative_int(entry.get("value"))
        if value is not None:
            total += value
    return total


def _working_set_bytes(
    memory_stats: dict[str, Any], cgroup_version: str
) -> int | None:
    usage = _optional_nonnegative_int(memory_stats.get("usage"))
    stats = memory_stats.get("stats")
    if usage is None or not isinstance(stats, dict):
        return None
    if cgroup_version == "1":
        inactive = _optional_nonnegative_int(stats.get("total_inactive_file"))
        if inactive is None:
            inactive = _optional_nonnegative_int(stats.get("inactive_file"))
    else:
        inactive = _optional_nonnegative_int(stats.get("inactive_file"))
        if inactive is None and cgroup_version == "unknown":
            inactive = _optional_nonnegative_int(stats.get("total_inactive_file"))
    if inactive is None:
        return None
    return max(0, usage - inactive)


@dataclass(frozen=True)
class DockerStatsSnapshot:
    observed_at: datetime
    monotonic_ns: int
    container_id: str
    cpu_total_usage_ns: int | None
    system_cpu_usage_ns: int | None
    online_cpus: int | None
    memory_usage_bytes: int | None
    memory_working_set_bytes: int | None
    docker_max_usage_bytes: int | None
    block_io_read_bytes: int | None
    block_io_write_bytes: int | None
    pids_current: int | None

    def has_measurement(self) -> bool:
        return any(
            value is not None
            for value in (
                self.cpu_total_usage_ns,
                self.memory_usage_bytes,
                self.memory_working_set_bytes,
                self.block_io_read_bytes,
                self.block_io_write_bytes,
                self.pids_current,
            )
        )


@dataclass(frozen=True)
class DockerSampleIssue:
    metric: str
    code: str
    error: BaseException

    def to_error(self) -> dict[str, str | None]:
        return {
            "source": "measurement",
            "code": self.code,
            "message": f"{self.metric}: {_bounded_message(self.error)}",
            "exception_type": self.error.__class__.__name__,
        }


@dataclass(frozen=True)
class DockerSampleResult:
    snapshot: DockerStatsSnapshot
    issues: tuple[DockerSampleIssue, ...] = ()


class DockerSampleSource(Protocol):
    container_id: str

    def collect(self) -> DockerSampleResult:
        ...

    def inspect_container(self) -> tuple[dict[str, object], list[dict[str, str | None]]]:
        ...

    def read_cgroup_v2_memory_peak(self) -> tuple[int | None, dict[str, str | None] | None]:
        ...

    def read_oom_killed(self) -> tuple[bool | None, dict[str, str | None] | None]:
        ...


def parse_docker_stats(
    raw: dict[str, Any],
    *,
    container_id: str,
    cgroup_version: str,
    observed_at: datetime,
    monotonic_ns: int,
) -> DockerStatsSnapshot:
    cpu_stats = raw.get("cpu_stats")
    cpu_stats = cpu_stats if isinstance(cpu_stats, dict) else {}
    cpu_usage = cpu_stats.get("cpu_usage")
    cpu_usage = cpu_usage if isinstance(cpu_usage, dict) else {}
    total_usage = _optional_nonnegative_int(cpu_usage.get("total_usage"))
    system_usage = _optional_nonnegative_int(cpu_stats.get("system_cpu_usage"))
    online_cpus = _optional_nonnegative_int(cpu_stats.get("online_cpus"))
    if online_cpus in {None, 0}:
        per_cpu = cpu_usage.get("percpu_usage")
        online_cpus = len(per_cpu) if isinstance(per_cpu, list) and per_cpu else None

    memory_stats = raw.get("memory_stats")
    memory_stats = memory_stats if isinstance(memory_stats, dict) else {}
    memory_usage = _optional_nonnegative_int(memory_stats.get("usage"))
    docker_max_usage = (
        _optional_nonnegative_int(memory_stats.get("max_usage"))
        if cgroup_version in {"1", "unknown"}
        else None
    )

    block_stats = raw.get("blkio_stats")
    block_stats = block_stats if isinstance(block_stats, dict) else {}
    service_bytes = block_stats.get("io_service_bytes_recursive")

    pids_stats = raw.get("pids_stats")
    pids_stats = pids_stats if isinstance(pids_stats, dict) else {}

    return DockerStatsSnapshot(
        observed_at=observed_at,
        monotonic_ns=monotonic_ns,
        container_id=container_id,
        cpu_total_usage_ns=total_usage,
        system_cpu_usage_ns=system_usage,
        online_cpus=online_cpus,
        memory_usage_bytes=memory_usage,
        memory_working_set_bytes=_working_set_bytes(memory_stats, cgroup_version),
        docker_max_usage_bytes=docker_max_usage,
        block_io_read_bytes=_sum_block_io(service_bytes, "read"),
        block_io_write_bytes=_sum_block_io(service_bytes, "write"),
        pids_current=_optional_nonnegative_int(pids_stats.get("current")),
    )


class DockerContainerSampleSource:
    def __init__(
        self,
        container: Any,
        *,
        cgroup_version: str = "unknown",
        utc_now: Callable[[], datetime] = _utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if cgroup_version not in {"1", "2", "unknown"}:
            raise ValueError(f"unsupported cgroup version: {cgroup_version}")
        self.container = container
        self.container_id = str(container.id)
        self.cgroup_version = cgroup_version
        self._utc_now = utc_now
        self._monotonic_ns = monotonic_ns
        api_version = getattr(getattr(container, "client", None), "api", None)
        self._api_version = getattr(api_version, "_version", None)

    def collect(self) -> DockerSampleResult:
        kwargs: dict[str, object] = {"stream": False}
        if _api_supports_one_shot(self._api_version):
            kwargs["one_shot"] = True
        raw = self.container.stats(**kwargs)
        if not isinstance(raw, dict):
            raise TypeError("Docker stats response is not an object")
        return DockerSampleResult(
            parse_docker_stats(
                raw,
                container_id=self.container_id,
                cgroup_version=self.cgroup_version,
                observed_at=self._utc_now(),
                monotonic_ns=self._monotonic_ns(),
            )
        )

    def inspect_container(
        self,
    ) -> tuple[dict[str, object], list[dict[str, str | None]]]:
        try:
            self.container.reload()
            attrs = self.container.attrs
            host_config = attrs.get("HostConfig", {})
            config = attrs.get("Config", {})
            memory_limit = _optional_nonnegative_int(host_config.get("Memory"))
            nano_cpus = _optional_nonnegative_int(host_config.get("NanoCpus"))
            pids_limit = _optional_nonnegative_int(host_config.get("PidsLimit"))
            return (
                {
                    "id": self.container_id,
                    "image": config.get("Image"),
                    "memory_limit_bytes": memory_limit or None,
                    "nano_cpus": nano_cpus or None,
                    "pids_limit": pids_limit or None,
                },
                [],
            )
        except Exception as error:
            return (
                {
                    "id": self.container_id,
                    "image": None,
                    "memory_limit_bytes": None,
                    "nano_cpus": None,
                    "pids_limit": None,
                },
                [
                    {
                        "source": "measurement",
                        "code": "container_inspect_failed",
                        "message": _bounded_message(error),
                        "exception_type": error.__class__.__name__,
                    }
                ],
            )

    def read_cgroup_v2_memory_peak(
        self,
    ) -> tuple[int | None, dict[str, str | None] | None]:
        if self.cgroup_version != "2":
            return None, None
        try:
            result = self.container.exec_run(
                ["cat", "/sys/fs/cgroup/memory.peak"], user="root"
            )
            if result.exit_code != 0:
                raise RuntimeError("memory.peak command returned a nonzero status")
            peak = int(result.output.decode("utf-8").strip())
            if peak < 0:
                raise ValueError("memory.peak was negative")
            return peak, None
        except Exception as error:
            return (
                None,
                {
                    "source": "measurement",
                    "code": "cgroup_memory_peak_unavailable",
                    "message": _bounded_message(error),
                    "exception_type": error.__class__.__name__,
                },
            )

    def read_oom_killed(
        self,
    ) -> tuple[bool | None, dict[str, str | None] | None]:
        try:
            self.container.reload()
            state = self.container.attrs.get("State", {})
            docker_oom = bool(state.get("OOMKilled", False))
            if self.cgroup_version != "2":
                return docker_oom, None

            result = self.container.exec_run(
                ["cat", "/sys/fs/cgroup/memory.events"], user="root"
            )
            if result.exit_code != 0:
                raise RuntimeError("memory.events command returned a nonzero status")
            events: dict[str, int] = {}
            for line in result.output.decode("utf-8").splitlines():
                name, value = line.split(maxsplit=1)
                events[name] = int(value)
            return docker_oom or events.get("oom_kill", 0) > 0, None
        except Exception as error:
            return (
                None,
                {
                    "source": "measurement",
                    "code": "oom_evidence_unavailable",
                    "message": _bounded_message(error),
                    "exception_type": error.__class__.__name__,
                },
            )


@dataclass
class _ResourceAccumulator:
    first: DockerStatsSnapshot | None = None
    last: DockerStatsSnapshot | None = None
    sample_count: int = 0
    memory_usage_peak: int | None = None
    memory_working_set_peak: int | None = None
    pids_peak: int | None = None
    cpu_percent_peak: float | None = None
    cpu_percent_weighted_sum: float = 0.0
    cpu_percent_weight_seconds: float = 0.0

    def add(
        self,
        snapshot: DockerStatsSnapshot,
        issue_callback: Callable[[DockerSampleIssue], None],
    ) -> None:
        previous = self.last
        if self.first is None:
            self.first = snapshot
        self.last = snapshot
        self.sample_count += 1

        if snapshot.memory_usage_bytes is not None:
            self.memory_usage_peak = (
                snapshot.memory_usage_bytes
                if self.memory_usage_peak is None
                else max(self.memory_usage_peak, snapshot.memory_usage_bytes)
            )
        if snapshot.memory_working_set_bytes is not None:
            self.memory_working_set_peak = (
                snapshot.memory_working_set_bytes
                if self.memory_working_set_peak is None
                else max(
                    self.memory_working_set_peak,
                    snapshot.memory_working_set_bytes,
                )
            )
        if snapshot.pids_current is not None:
            self.pids_peak = (
                snapshot.pids_current
                if self.pids_peak is None
                else max(self.pids_peak, snapshot.pids_current)
            )
        if previous is not None:
            self._add_cpu_percent(previous, snapshot, issue_callback)

    def _add_cpu_percent(
        self,
        previous: DockerStatsSnapshot,
        current: DockerStatsSnapshot,
        issue_callback: Callable[[DockerSampleIssue], None],
    ) -> None:
        values = (
            previous.cpu_total_usage_ns,
            current.cpu_total_usage_ns,
            previous.system_cpu_usage_ns,
            current.system_cpu_usage_ns,
            current.online_cpus,
        )
        if any(value is None for value in values):
            return
        container_delta = current.cpu_total_usage_ns - previous.cpu_total_usage_ns
        system_delta = current.system_cpu_usage_ns - previous.system_cpu_usage_ns
        elapsed_seconds = (current.monotonic_ns - previous.monotonic_ns) / 1e9
        if container_delta < 0 or system_delta <= 0 or elapsed_seconds <= 0:
            issue_callback(
                DockerSampleIssue(
                    "container.cpu",
                    "container_cpu_counter_reset",
                    ValueError("Docker CPU counters or monotonic time did not increase"),
                )
            )
            return
        cpu_percent = 100.0 * container_delta / system_delta * current.online_cpus
        cpu_percent = max(0.0, cpu_percent)
        self.cpu_percent_peak = (
            cpu_percent
            if self.cpu_percent_peak is None
            else max(self.cpu_percent_peak, cpu_percent)
        )
        self.cpu_percent_weighted_sum += cpu_percent * elapsed_seconds
        self.cpu_percent_weight_seconds += elapsed_seconds

    def _counter_delta(
        self,
        attribute: str,
        metric: str,
        issue_callback: Callable[[DockerSampleIssue], None],
    ) -> int | None:
        if self.sample_count < 2 or self.first is None or self.last is None:
            return None
        start = getattr(self.first, attribute)
        end = getattr(self.last, attribute)
        if start is None or end is None:
            return None
        if end < start:
            issue_callback(
                DockerSampleIssue(
                    metric,
                    "container_counter_reset",
                    ValueError(f"{metric} decreased during measurement"),
                )
            )
            return None
        return end - start

    def to_metrics(
        self,
        wall_time_seconds: float | None,
        issue_callback: Callable[[DockerSampleIssue], None],
    ) -> dict[str, int | float | None]:
        return {
            "wall_time_seconds": wall_time_seconds,
            "cpu_usage_ns": self._counter_delta(
                "cpu_total_usage_ns", "container.cpu_usage", issue_callback
            ),
            "cpu_percent_mean": (
                self.cpu_percent_weighted_sum / self.cpu_percent_weight_seconds
                if self.cpu_percent_weight_seconds > 0
                else None
            ),
            "cpu_percent_peak": self.cpu_percent_peak,
            "memory_usage_sampled_peak_bytes": self.memory_usage_peak,
            "memory_working_set_sampled_peak_bytes": self.memory_working_set_peak,
            "block_io_read_bytes": self._counter_delta(
                "block_io_read_bytes", "container.block_io_read", issue_callback
            ),
            "block_io_write_bytes": self._counter_delta(
                "block_io_write_bytes", "container.block_io_write", issue_callback
            ),
            "pids_sampled_peak": self.pids_peak,
            "sample_count": self.sample_count,
        }


@dataclass
class _PhaseAccumulator:
    name: str
    started_at: datetime
    started_monotonic_ns: int
    resources: _ResourceAccumulator = field(default_factory=_ResourceAccumulator)
    state: str | None = None
    ended_at: datetime | None = None
    ended_monotonic_ns: int | None = None

    def finish(self, state: str, ended_at: datetime, ended_monotonic_ns: int) -> None:
        self.state = state
        self.ended_at = ended_at
        self.ended_monotonic_ns = ended_monotonic_ns

    def to_record(
        self, issue_callback: Callable[[DockerSampleIssue], None]
    ) -> dict[str, object]:
        wall_time = (
            max(0.0, (self.ended_monotonic_ns - self.started_monotonic_ns) / 1e9)
            if self.ended_monotonic_ns is not None
            else None
        )
        return {
            "state": self.state or "interrupted",
            "started_at": _format_timestamp(self.started_at),
            "ended_at": _format_timestamp(self.ended_at),
            "metrics": self.resources.to_metrics(wall_time, issue_callback),
        }


class DockerContainerSampler:
    def __init__(
        self,
        source: DockerSampleSource,
        *,
        interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
        utc_now: Callable[[], datetime] = _utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        self.source = source
        self.interval_seconds = interval_seconds
        self._utc_now = utc_now
        self._monotonic_ns = monotonic_ns
        self._resources = _ResourceAccumulator()
        self._phases: dict[str, _PhaseAccumulator] = {}
        self._active_phase: str | None = None
        self._errors: dict[tuple[str, str], dict[str, str | None]] = {}
        self._attempted_samples = 0
        self._successful_samples = 0
        self._failed_samples = 0
        self._first_sample_at: datetime | None = None
        self._last_sample_at: datetime | None = None
        self._docker_max_usage_peak: int | None = None
        self._lock = threading.RLock()
        self._collect_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopped = False
        self._started_at: datetime | None = None
        self._started_monotonic_ns: int | None = None
        self._ended_at: datetime | None = None
        self._ended_monotonic_ns: int | None = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                raise RuntimeError("container sampler has already been started")
            self._started = True
            self._started_at = self._utc_now()
            self._started_monotonic_ns = self._monotonic_ns()
        self._sample_once()
        self._thread = threading.Thread(
            target=self._run,
            name=f"docker-resource-sampler-{self.source.container_id[:12]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                raise RuntimeError("container sampler has not been started")
            if self._stopped:
                return
            self._stopped = True
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5.0, self.interval_seconds * 2))
            if self._thread.is_alive():
                self._add_issue(
                    DockerSampleIssue(
                        "container.sampler",
                        "container_sampler_stop_timeout",
                        TimeoutError("sampler thread did not stop before timeout"),
                    )
                )
                return
        if self._active_phase is not None:
            self.end_phase("interrupted")
        self._sample_once()
        with self._lock:
            self._ended_at = self._utc_now()
            self._ended_monotonic_ns = self._monotonic_ns()

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self._sample_once()

    def _sample_once(self) -> None:
        with self._collect_lock:
            try:
                result = self.source.collect()
            except Exception as error:
                with self._lock:
                    self._attempted_samples += 1
                    self._failed_samples += 1
                    self._add_issue(
                        DockerSampleIssue(
                            "container.stats", "docker_stats_failed", error
                        )
                    )
                return

            with self._lock:
                self._attempted_samples += 1
                snapshot = result.snapshot
                if snapshot.container_id != self.source.container_id:
                    self._failed_samples += 1
                    self._add_issue(
                        DockerSampleIssue(
                            "container.identity",
                            "container_identity_changed",
                            ValueError(
                                "Docker statistics came from a different container"
                            ),
                        )
                    )
                    return
                if snapshot.has_measurement():
                    self._successful_samples += 1
                    if self._first_sample_at is None:
                        self._first_sample_at = snapshot.observed_at
                    self._last_sample_at = snapshot.observed_at
                else:
                    self._failed_samples += 1
                for issue in result.issues:
                    self._add_issue(issue)
                self._resources.add(snapshot, self._add_issue)
                if snapshot.docker_max_usage_bytes is not None:
                    self._docker_max_usage_peak = (
                        snapshot.docker_max_usage_bytes
                        if self._docker_max_usage_peak is None
                        else max(
                            self._docker_max_usage_peak,
                            snapshot.docker_max_usage_bytes,
                        )
                    )
                if self._active_phase is not None:
                    self._phases[self._active_phase].resources.add(
                        snapshot, self._add_issue
                    )

    def begin_phase(self, name: str) -> None:
        if name not in PHASE_NAMES:
            raise ValueError(f"unsupported resource phase: {name}")
        with self._lock:
            if not self._started or self._stopped:
                raise RuntimeError("container sampler is not running")
            if self._active_phase is not None:
                raise RuntimeError(f"resource phase already active: {self._active_phase}")
            if name in self._phases:
                raise RuntimeError(f"resource phase already recorded: {name}")
            self._active_phase = name
            self._phases[name] = _PhaseAccumulator(
                name=name,
                started_at=self._utc_now(),
                started_monotonic_ns=self._monotonic_ns(),
            )
        self._sample_once()

    def end_phase(self, state: str = "completed") -> None:
        if state not in PHASE_STATES - {"skipped"}:
            raise ValueError(f"unsupported completed phase state: {state}")
        with self._lock:
            if self._active_phase is None:
                raise RuntimeError("no resource phase is active")
        self._sample_once()
        with self._lock:
            name = self._active_phase
            if name is None:
                raise RuntimeError("resource phase ended concurrently")
            self._phases[name].finish(
                state,
                ended_at=self._utc_now(),
                ended_monotonic_ns=self._monotonic_ns(),
            )
            self._active_phase = None

    @contextlib.contextmanager
    def phase(self, name: str) -> Iterator[PhaseHandle]:
        self.begin_phase(name)
        handle = PhaseHandle()
        try:
            yield handle
        except (KeyboardInterrupt, SystemExit):
            self.end_phase("interrupted")
            raise
        except TimeoutError:
            self.end_phase("timed_out")
            raise
        except Exception:
            self.end_phase("failed")
            raise
        else:
            self.end_phase(handle.state)

    def _add_issue(self, issue: DockerSampleIssue) -> None:
        with self._lock:
            self._errors.setdefault((issue.metric, issue.code), issue.to_error())

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            wall_time = (
                max(
                    0.0,
                    (self._ended_monotonic_ns - self._started_monotonic_ns) / 1e9,
                )
                if self._ended_monotonic_ns is not None
                and self._started_monotonic_ns is not None
                else None
            )
            phases = {
                name: phase.to_record(self._add_issue)
                for name, phase in self._phases.items()
            }
            return {
                "started_at": _format_timestamp(self._started_at),
                "ended_at": _format_timestamp(self._ended_at),
                "wall_time_seconds": wall_time,
                "sampling": {
                    "interval_seconds": self.interval_seconds,
                    "attempted_samples": self._attempted_samples,
                    "successful_samples": self._successful_samples,
                    "failed_samples": self._failed_samples,
                    "first_sample_at": _format_timestamp(self._first_sample_at),
                    "last_sample_at": _format_timestamp(self._last_sample_at),
                },
                "container_metrics": self._resources.to_metrics(
                    wall_time, self._add_issue
                ),
                "phases": phases,
                "docker_max_usage_peak_bytes": self._docker_max_usage_peak,
                "errors": list(self._errors.values()),
            }

    def current_working_set_bytes(self) -> int | None:
        with self._lock:
            if self._resources.last is None:
                return None
            return self._resources.last.memory_working_set_bytes

    def active_phase(self) -> str | None:
        with self._lock:
            return self._active_phase


@dataclass
class PhaseHandle:
    state: str = "completed"

    def mark_timed_out(self) -> None:
        self.state = "timed_out"

    def mark_failed(self) -> None:
        self.state = "failed"


@dataclass(frozen=True)
class InstanceResourceConfig:
    run_id: str
    agent: str
    instance_id: str


@dataclass(frozen=True)
class InstanceOutcome:
    state: str = "completed"
    failure_kind: str | None = None
    failed_phase: str | None = None
    evaluation_completed: bool | None = None
    resolved: bool | None = None

    def __post_init__(self) -> None:
        if self.state not in {"completed", "partial", "failed", "interrupted"}:
            raise ValueError(f"unsupported instance state: {self.state}")
        failure_kinds = {
            None,
            "timeout",
            "oom_killed",
            "patch_error",
            "docker_error",
            "tracer_error",
            "evaluation_error",
            "cancelled",
            "unknown_error",
        }
        if self.failure_kind not in failure_kinds:
            raise ValueError(f"unsupported failure kind: {self.failure_kind}")

    def to_record(self) -> dict[str, object]:
        return {
            "state": self.state,
            "failure_kind": self.failure_kind,
            "failed_phase": self.failed_phase,
            "evaluation_completed": self.evaluation_completed,
            "resolved": self.resolved,
        }


@dataclass(frozen=True)
class ArtifactStats:
    state: str = "missing"
    file_count: int = 0
    total_bytes: int = 0
    largest_file_bytes: int = 0
    event_count: int | None = None

    def __post_init__(self) -> None:
        if self.state not in {"complete", "partial", "missing"}:
            raise ValueError(f"unsupported artifact state: {self.state}")
        values = (self.file_count, self.total_bytes, self.largest_file_bytes)
        if any(value < 0 for value in values):
            raise ValueError("artifact metrics cannot be negative")
        if self.event_count is not None and self.event_count < 0:
            raise ValueError("event_count cannot be negative")

    def to_record(self) -> dict[str, object]:
        return {
            "state": self.state,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "largest_file_bytes": self.largest_file_bytes,
            "event_count": self.event_count,
        }


def collect_artifact_stats(
    artifact_path: str | os.PathLike[str],
) -> tuple[ArtifactStats, list[dict[str, str | None]]]:
    """Collect trace sizes from filesystem metadata without opening contents."""
    root = Path(artifact_path)
    pending = [root]
    file_count = 0
    total_bytes = 0
    largest_file_bytes = 0
    errors: list[dict[str, str | None]] = []

    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError as error:
                        errors.append(_artifact_scan_error(entry.path, error))
                        continue
                    if stat.S_ISDIR(entry_stat.st_mode):
                        pending.append(Path(entry.path))
                    elif stat.S_ISREG(entry_stat.st_mode):
                        file_count += 1
                        total_bytes += entry_stat.st_size
                        largest_file_bytes = max(
                            largest_file_bytes, entry_stat.st_size
                        )
        except FileNotFoundError as error:
            if directory == root and not errors and file_count == 0:
                return ArtifactStats(), []
            errors.append(_artifact_scan_error(directory, error))
        except OSError as error:
            errors.append(_artifact_scan_error(directory, error))

    return (
        ArtifactStats(
            state="partial" if errors else "complete",
            file_count=file_count,
            total_bytes=total_bytes,
            largest_file_bytes=largest_file_bytes,
        ),
        errors,
    )


def _artifact_scan_error(
    path: str | os.PathLike[str], error: OSError
) -> dict[str, str | None]:
    return {
        "source": "measurement",
        "code": "artifact_scan_failed",
        "message": f"{path}: {_bounded_message(error)}"[:500],
        "exception_type": error.__class__.__name__,
    }


class InstanceResourceMonitor:
    def __init__(
        self,
        config: InstanceResourceConfig,
        container: Any,
        output_path: str | os.PathLike[str],
        *,
        cgroup_version: str = "unknown",
        interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
        sample_source: DockerSampleSource | None = None,
        utc_now: Callable[[], datetime] = _utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.config = config
        self.output_path = Path(output_path)
        self.source = sample_source or DockerContainerSampleSource(
            container,
            cgroup_version=cgroup_version,
            utc_now=utc_now,
            monotonic_ns=monotonic_ns,
        )
        self.sampler = DockerContainerSampler(
            self.source,
            interval_seconds=interval_seconds,
            utc_now=utc_now,
            monotonic_ns=monotonic_ns,
        )
        self._utc_now = utc_now
        self._record: dict[str, object] | None = None
        self._context_outcome: InstanceOutcome | None = None
        self._context_buggy_artifact: ArtifactStats | None = None
        self._context_patched_artifact: ArtifactStats | None = None

    def start(self) -> InstanceResourceMonitor:
        self.sampler.start()
        return self

    def set_context_result(
        self,
        outcome: InstanceOutcome,
        *,
        buggy_artifact: ArtifactStats | None = None,
        patched_artifact: ArtifactStats | None = None,
    ) -> None:
        self._context_outcome = outcome
        self._context_buggy_artifact = buggy_artifact
        self._context_patched_artifact = patched_artifact

    def stop(
        self,
        outcome: InstanceOutcome | None = None,
        *,
        buggy_artifact: ArtifactStats | None = None,
        patched_artifact: ArtifactStats | None = None,
        workload_errors: Sequence[dict[str, str | None]] = (),
    ) -> dict[str, object]:
        if self._record is not None:
            return self._record
        self.sampler.stop()
        snapshot = self.sampler.snapshot()
        container, inspect_errors = self.source.inspect_container()
        outcome = outcome or InstanceOutcome()

        lifetime_peak = snapshot["docker_max_usage_peak_bytes"]
        lifetime_source = "docker_max_usage" if lifetime_peak is not None else None
        cgroup_peak, cgroup_peak_error = self.source.read_cgroup_v2_memory_peak()
        if cgroup_peak is not None:
            lifetime_peak = cgroup_peak
            lifetime_source = "cgroup_memory_peak"
        oom_killed, oom_error = self.source.read_oom_killed()
        if oom_killed is True and outcome.state != "completed":
            outcome = replace(outcome, failure_kind="oom_killed")
        container.update(
            {
                "lifetime_peak_memory_bytes": lifetime_peak,
                "lifetime_peak_memory_source": lifetime_source,
                "oom_killed": oom_killed,
            }
        )

        buggy = buggy_artifact or ArtifactStats()
        patched = patched_artifact or ArtifactStats()
        errors = [
            *snapshot["errors"],
            *inspect_errors,
            *([cgroup_peak_error] if cgroup_peak_error is not None else []),
            *([oom_error] if oom_error is not None else []),
            *workload_errors,
        ]
        measurement = self._measurement_status(snapshot, buggy, patched)
        record = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "instance",
            "generated_at": _format_timestamp(self._utc_now()),
            "run_id": self.config.run_id,
            "agent": self.config.agent,
            "instance_id": self.config.instance_id,
            "container": container,
            "started_at": snapshot["started_at"],
            "ended_at": snapshot["ended_at"],
            "wall_time_seconds": snapshot["wall_time_seconds"],
            "outcome": outcome.to_record(),
            "measurement": measurement,
            "sampling": snapshot["sampling"],
            "container_metrics": snapshot["container_metrics"],
            "phases": snapshot["phases"],
            "artifacts": {
                "buggy": buggy.to_record(),
                "patched": patched.to_record(),
            },
            "errors": errors,
        }
        _atomic_write_json(self.output_path, record)
        self._record = record
        return record

    @staticmethod
    def _measurement_status(
        snapshot: dict[str, object],
        buggy_artifact: ArtifactStats,
        patched_artifact: ArtifactStats,
    ) -> dict[str, object]:
        metrics = snapshot["container_metrics"]
        fields = {
            "cpu_usage_ns": "container.cpu_usage_ns",
            "memory_usage_sampled_peak_bytes": "container.memory_usage_bytes",
            "memory_working_set_sampled_peak_bytes": (
                "container.memory_working_set_bytes"
            ),
            "block_io_read_bytes": "container.block_io_read_bytes",
            "block_io_write_bytes": "container.block_io_write_bytes",
            "pids_sampled_peak": "container.pids_current",
        }
        missing = [path for name, path in fields.items() if metrics.get(name) is None]
        if buggy_artifact.state == "missing":
            missing.append("artifacts.buggy")
        if patched_artifact.state == "missing":
            missing.append("artifacts.patched")

        core_values = (
            snapshot.get("wall_time_seconds"),
            metrics.get("cpu_usage_ns"),
            metrics.get("memory_usage_sampled_peak_bytes"),
            buggy_artifact.total_bytes if buggy_artifact.state != "missing" else None,
            patched_artifact.total_bytes if patched_artifact.state != "missing" else None,
        )
        available_core = sum(value is not None for value in core_values)
        state = (
            "unavailable"
            if available_core == 0
            else "partial"
            if missing
            else "complete"
        )
        return {"state": state, "missing_metrics": sorted(missing)}

    def __enter__(self) -> InstanceResourceMonitor:
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        workload_errors: list[dict[str, str | None]] = []
        if exc_type is not None and issubclass(
            exc_type, (KeyboardInterrupt, SystemExit)
        ):
            outcome = InstanceOutcome(
                state="interrupted", failure_kind="cancelled"
            )
        elif exc_type is not None and issubclass(exc_type, TimeoutError):
            outcome = InstanceOutcome(state="partial", failure_kind="timeout")
        elif exc_type is not None:
            outcome = InstanceOutcome(state="failed", failure_kind="unknown_error")
        else:
            outcome = self._context_outcome or InstanceOutcome()

        if exc_value is not None:
            workload_errors.append(
                {
                    "source": "workload",
                    "code": "instance_monitor_context_error",
                    "message": _bounded_message(exc_value),
                    "exception_type": exc_type.__name__ if exc_type else None,
                }
            )
        try:
            self.stop(
                outcome,
                buggy_artifact=self._context_buggy_artifact,
                patched_artifact=self._context_patched_artifact,
                workload_errors=workload_errors,
            )
        except Exception:
            if exc_type is None:
                raise
        return False


class DockerRunAggregateProvider:
    def __init__(
        self,
        docker_client: Any,
        run_id: str,
        *,
        cgroup_version: str = "unknown",
    ) -> None:
        self.client = docker_client
        self.run_id = run_id
        self.cgroup_version = cgroup_version

    def __call__(self) -> ContainerAggregate:
        suffix = f".{self.run_id}"
        containers = self.client.containers.list(filters={"name": self.run_id})
        containers = [
            container for container in containers if container.name.endswith(suffix)
        ]
        total_working_set = 0
        for container in containers:
            kwargs: dict[str, object] = {"stream": False}
            api_version = getattr(
                getattr(getattr(container, "client", None), "api", None),
                "_version",
                None,
            )
            if _api_supports_one_shot(api_version):
                kwargs["one_shot"] = True
            raw = container.stats(**kwargs)
            memory_stats = raw.get("memory_stats", {})
            working_set = _working_set_bytes(memory_stats, self.cgroup_version)
            if working_set is None:
                return ContainerAggregate(len(containers), None)
            total_working_set += working_set
        return ContainerAggregate(len(containers), total_working_set)
