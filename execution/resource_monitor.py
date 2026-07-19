from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import tempfile
import threading
import time

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


SCHEMA_VERSION = 1
DEFAULT_SAMPLE_INTERVAL_SECONDS = 1.0
RUN_RESOURCE_FILENAME = "resource_usage.run.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_message(error: BaseException, limit: int = 500) -> str:
    message = str(error).replace("\n", " ").strip()
    if not message:
        message = error.__class__.__name__
    return message[:limit]


@dataclass(frozen=True)
class CpuCounters:
    total: int
    idle: int


@dataclass(frozen=True)
class FilesystemReading:
    total_bytes: int
    available_bytes: int


@dataclass(frozen=True)
class ContainerAggregate:
    active_count: int | None
    working_set_bytes: int | None


@dataclass(frozen=True)
class SampleIssue:
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
class HostSample:
    observed_at: datetime
    monotonic_ns: int
    cpu: CpuCounters | None
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    swap_total_bytes: int | None
    swap_free_bytes: int | None
    load1: float | None
    filesystems: dict[str, FilesystemReading | None]
    containers: ContainerAggregate

    def has_measurement(self) -> bool:
        return any(
            (
                self.cpu is not None,
                self.memory_total_bytes is not None,
                self.memory_available_bytes is not None,
                self.swap_total_bytes is not None,
                self.swap_free_bytes is not None,
                self.load1 is not None,
                any(value is not None for value in self.filesystems.values()),
                self.containers.active_count is not None,
                self.containers.working_set_bytes is not None,
            )
        )


@dataclass(frozen=True)
class SampleResult:
    sample: HostSample
    issues: tuple[SampleIssue, ...] = ()


class HostSampleSource(Protocol):
    filesystem_paths: dict[str, str]

    def collect(self) -> SampleResult:
        ...


def _parse_proc_stat(content: str) -> CpuCounters:
    for line in content.splitlines():
        fields = line.split()
        if not fields or fields[0] != "cpu":
            continue
        values = [int(value) for value in fields[1:]]
        if len(values) < 4:
            raise ValueError("aggregate cpu row has fewer than four counters")
        values.extend([0] * (8 - len(values)))
        user, nice, system, idle, iowait, irq, softirq, steal = values[:8]
        return CpuCounters(
            total=user + nice + system + idle + iowait + irq + softirq + steal,
            idle=idle + iowait,
        )
    raise ValueError("aggregate cpu row is missing")


def _parse_meminfo(content: str) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for line in content.splitlines():
        key, separator, remainder = line.partition(":")
        if not separator:
            continue
        fields = remainder.split()
        if not fields:
            continue
        value = int(fields[0])
        if len(fields) > 1 and fields[1] == "kB":
            value *= 1024
        parsed[key] = value
    required = ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")
    missing = [key for key in required if key not in parsed]
    if missing:
        raise ValueError(f"missing meminfo fields: {', '.join(missing)}")
    return parsed


def _read_os_release(path: Path = Path("/etc/os-release")) -> str:
    try:
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value.strip().strip('"')
        return values.get("PRETTY_NAME") or values.get("NAME") or platform.platform()
    except OSError:
        return platform.platform()


def _read_cpu_model(path: Path = Path("/proc/cpuinfo")) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() in {"model name", "Hardware", "Processor"}:
                model = value.strip()
                if model:
                    return model
    except OSError:
        pass
    return platform.processor() or None


def _nearest_existing_path(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _read_filesystem(path: str) -> FilesystemReading:
    stat = os.statvfs(_nearest_existing_path(Path(path)))
    return FilesystemReading(
        total_bytes=stat.f_blocks * stat.f_frsize,
        available_bytes=stat.f_bavail * stat.f_frsize,
    )


class LinuxHostSampleSource:
    def __init__(
        self,
        trace_output_path: str | os.PathLike[str],
        docker_data_root: str | os.PathLike[str] | None,
        *,
        container_aggregate_provider: Callable[[], ContainerAggregate] | None = None,
        proc_root: str | os.PathLike[str] = "/proc",
        utc_now: Callable[[], datetime] = _utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._proc_root = Path(proc_root)
        self._container_aggregate_provider = container_aggregate_provider
        self._utc_now = utc_now
        self._monotonic_ns = monotonic_ns
        self.filesystem_paths = {
            "trace_output": str(Path(trace_output_path).expanduser().absolute()),
            "docker_data_root": (
                str(Path(docker_data_root).expanduser().absolute())
                if docker_data_root and str(docker_data_root) != "unknown"
                else "unknown"
            ),
        }

    def collect(self) -> SampleResult:
        issues: list[SampleIssue] = []

        try:
            cpu = _parse_proc_stat(
                (self._proc_root / "stat").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            cpu = None
            issues.append(SampleIssue("host.cpu", "host_cpu_unavailable", error))

        try:
            meminfo = _parse_meminfo(
                (self._proc_root / "meminfo").read_text(encoding="utf-8")
            )
            memory_total = meminfo["MemTotal"]
            memory_available = meminfo["MemAvailable"]
            swap_total = meminfo["SwapTotal"]
            swap_free = meminfo["SwapFree"]
        except (OSError, ValueError) as error:
            memory_total = None
            memory_available = None
            swap_total = None
            swap_free = None
            issues.append(
                SampleIssue("host.memory", "host_memory_unavailable", error)
            )

        try:
            load1 = float(
                (self._proc_root / "loadavg")
                .read_text(encoding="utf-8")
                .split(maxsplit=1)[0]
            )
        except (OSError, ValueError, IndexError) as error:
            load1 = None
            issues.append(SampleIssue("host.load1", "host_load_unavailable", error))

        filesystems: dict[str, FilesystemReading | None] = {}
        for role, path in self.filesystem_paths.items():
            if path == "unknown":
                filesystems[role] = None
                continue
            try:
                filesystems[role] = _read_filesystem(path)
            except OSError as error:
                filesystems[role] = None
                issues.append(
                    SampleIssue(
                        f"filesystem.{role}",
                        "filesystem_unavailable",
                        error,
                    )
                )

        if self._container_aggregate_provider is None:
            containers = ContainerAggregate(None, None)
        else:
            try:
                containers = self._container_aggregate_provider()
            except Exception as error:
                containers = ContainerAggregate(None, None)
                issues.append(
                    SampleIssue(
                        "containers.aggregate",
                        "container_aggregate_unavailable",
                        error,
                    )
                )

        return SampleResult(
            sample=HostSample(
                observed_at=self._utc_now(),
                monotonic_ns=self._monotonic_ns(),
                cpu=cpu,
                memory_total_bytes=memory_total,
                memory_available_bytes=memory_available,
                swap_total_bytes=swap_total,
                swap_free_bytes=swap_free,
                load1=load1,
                filesystems=filesystems,
                containers=containers,
            ),
            issues=tuple(issues),
        )


@dataclass
class _FilesystemAccumulator:
    path: str
    total_bytes: int | None = None
    available_start_bytes: int | None = None
    available_min_bytes: int | None = None
    available_end_bytes: int | None = None

    def add(self, reading: FilesystemReading | None) -> None:
        if reading is None:
            return
        if self.total_bytes is None:
            self.total_bytes = reading.total_bytes
        if self.available_start_bytes is None:
            self.available_start_bytes = reading.available_bytes
        self.available_min_bytes = (
            reading.available_bytes
            if self.available_min_bytes is None
            else min(self.available_min_bytes, reading.available_bytes)
        )
        self.available_end_bytes = reading.available_bytes

    def to_record(self, role: str) -> dict[str, str | int | None]:
        return {
            "role": role,
            "path": self.path,
            "total_bytes": self.total_bytes,
            "available_start_bytes": self.available_start_bytes,
            "available_min_bytes": self.available_min_bytes,
            "available_end_bytes": self.available_end_bytes,
        }


@dataclass
class _HostAccumulator:
    filesystem_paths: dict[str, str]
    attempted_samples: int = 0
    successful_samples: int = 0
    failed_samples: int = 0
    first_sample_at: datetime | None = None
    last_sample_at: datetime | None = None
    memory_used_peak: int | None = None
    memory_available_min: int | None = None
    swap_used_peak: int | None = None
    load1_peak: float | None = None
    active_containers_peak: int | None = None
    aggregate_working_set_peak: int | None = None
    cpu_percent_peak: float | None = None
    cpu_percent_weighted_sum: float = 0.0
    cpu_percent_weight_seconds: float = 0.0
    previous_cpu: CpuCounters | None = None
    previous_cpu_monotonic_ns: int | None = None
    errors: dict[tuple[str, str], dict[str, str | None]] = field(default_factory=dict)
    filesystems: dict[str, _FilesystemAccumulator] = field(init=False)

    def __post_init__(self) -> None:
        self.filesystems = {
            role: _FilesystemAccumulator(path=path)
            for role, path in self.filesystem_paths.items()
        }

    def add_failure(self, error: BaseException) -> None:
        self.attempted_samples += 1
        self.failed_samples += 1
        issue = SampleIssue("host.sample", "host_sample_failed", error)
        self._add_issue(issue)

    def add(self, result: SampleResult) -> None:
        self.attempted_samples += 1
        sample = result.sample
        if sample.has_measurement():
            self.successful_samples += 1
            if self.first_sample_at is None:
                self.first_sample_at = sample.observed_at
            self.last_sample_at = sample.observed_at
        else:
            self.failed_samples += 1

        for issue in result.issues:
            self._add_issue(issue)

        self._add_cpu(sample)

        if (
            sample.memory_total_bytes is not None
            and sample.memory_available_bytes is not None
        ):
            memory_used = max(
                0, sample.memory_total_bytes - sample.memory_available_bytes
            )
            self.memory_used_peak = (
                memory_used
                if self.memory_used_peak is None
                else max(self.memory_used_peak, memory_used)
            )
            self.memory_available_min = (
                sample.memory_available_bytes
                if self.memory_available_min is None
                else min(self.memory_available_min, sample.memory_available_bytes)
            )

        if sample.swap_total_bytes is not None and sample.swap_free_bytes is not None:
            swap_used = max(0, sample.swap_total_bytes - sample.swap_free_bytes)
            self.swap_used_peak = (
                swap_used
                if self.swap_used_peak is None
                else max(self.swap_used_peak, swap_used)
            )

        if sample.load1 is not None:
            self.load1_peak = (
                sample.load1
                if self.load1_peak is None
                else max(self.load1_peak, sample.load1)
            )

        if sample.containers.active_count is not None:
            self.active_containers_peak = (
                sample.containers.active_count
                if self.active_containers_peak is None
                else max(self.active_containers_peak, sample.containers.active_count)
            )

        if sample.containers.working_set_bytes is not None:
            self.aggregate_working_set_peak = (
                sample.containers.working_set_bytes
                if self.aggregate_working_set_peak is None
                else max(
                    self.aggregate_working_set_peak,
                    sample.containers.working_set_bytes,
                )
            )

        for role, reading in sample.filesystems.items():
            if role in self.filesystems:
                self.filesystems[role].add(reading)

    def _add_issue(self, issue: SampleIssue) -> None:
        key = (issue.metric, issue.code)
        self.errors.setdefault(key, issue.to_error())

    def _add_cpu(self, sample: HostSample) -> None:
        if sample.cpu is None:
            return
        previous = self.previous_cpu
        previous_ns = self.previous_cpu_monotonic_ns
        self.previous_cpu = sample.cpu
        self.previous_cpu_monotonic_ns = sample.monotonic_ns
        if previous is None or previous_ns is None:
            return

        total_delta = sample.cpu.total - previous.total
        idle_delta = sample.cpu.idle - previous.idle
        elapsed_seconds = (sample.monotonic_ns - previous_ns) / 1e9
        if total_delta <= 0 or idle_delta < 0 or elapsed_seconds <= 0:
            self._add_issue(
                SampleIssue(
                    "host.cpu",
                    "host_cpu_counter_reset",
                    ValueError("CPU counters or monotonic time did not increase"),
                )
            )
            return

        cpu_percent = 100.0 * (total_delta - idle_delta) / total_delta
        cpu_percent = min(100.0, max(0.0, cpu_percent))
        self.cpu_percent_peak = (
            cpu_percent
            if self.cpu_percent_peak is None
            else max(self.cpu_percent_peak, cpu_percent)
        )
        self.cpu_percent_weighted_sum += cpu_percent * elapsed_seconds
        self.cpu_percent_weight_seconds += elapsed_seconds

    def cpu_percent_mean(self) -> float | None:
        if self.cpu_percent_weight_seconds <= 0:
            return None
        return self.cpu_percent_weighted_sum / self.cpu_percent_weight_seconds


class HostResourceSampler:
    def __init__(
        self,
        source: HostSampleSource,
        *,
        interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        self.source = source
        self.interval_seconds = interval_seconds
        self._accumulator = _HostAccumulator(source.filesystem_paths)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopped = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                raise RuntimeError("host sampler has already been started")
            self._started = True
        self._sample_once()
        self._thread = threading.Thread(
            target=self._run,
            name="execution-trace-host-resource-sampler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                raise RuntimeError("host sampler has not been started")
            if self._stopped:
                return
            self._stopped = True
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5.0, self.interval_seconds * 2))
            if self._thread.is_alive():
                with self._lock:
                    self._accumulator._add_issue(
                        SampleIssue(
                            "host.sampler",
                            "host_sampler_stop_timeout",
                            TimeoutError("sampler thread did not stop before timeout"),
                        )
                    )
                return
        self._sample_once()

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self._sample_once()

    def _sample_once(self) -> None:
        try:
            result = self.source.collect()
        except Exception as error:
            with self._lock:
                self._accumulator.add_failure(error)
            return
        with self._lock:
            self._accumulator.add(result)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            accumulator = self._accumulator
            return {
                "sampling": {
                    "interval_seconds": self.interval_seconds,
                    "attempted_samples": accumulator.attempted_samples,
                    "successful_samples": accumulator.successful_samples,
                    "failed_samples": accumulator.failed_samples,
                    "first_sample_at": _format_timestamp(accumulator.first_sample_at),
                    "last_sample_at": _format_timestamp(accumulator.last_sample_at),
                },
                "metrics": {
                    "memory_used_sampled_peak_bytes": accumulator.memory_used_peak,
                    "memory_available_sampled_min_bytes": accumulator.memory_available_min,
                    "swap_used_sampled_peak_bytes": accumulator.swap_used_peak,
                    "cpu_percent_mean": accumulator.cpu_percent_mean(),
                    "cpu_percent_peak": accumulator.cpu_percent_peak,
                    "load1_sampled_peak": accumulator.load1_peak,
                    "active_trace_containers_peak": accumulator.active_containers_peak,
                    "aggregate_container_working_set_sampled_peak_bytes": (
                        accumulator.aggregate_working_set_peak
                    ),
                },
                "filesystems": [
                    accumulator.filesystems[role].to_record(role)
                    for role in ("trace_output", "docker_data_root")
                    if role in accumulator.filesystems
                ],
                "errors": list(accumulator.errors.values()),
            }


@dataclass(frozen=True)
class RunResourceConfig:
    run_id: str
    agent: str
    instance_selection: Sequence[str]
    resolved_instance_ids: Sequence[str]
    max_workers: int
    timeout_seconds: float | None
    cache_state: str = "unknown"

    def __post_init__(self) -> None:
        if self.max_workers < 1:
            raise ValueError("max_workers must be at least one")
        if self.timeout_seconds is not None and self.timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
        if self.cache_state not in {"cold", "warm", "mixed", "unknown"}:
            raise ValueError(f"unsupported cache_state: {self.cache_state}")


@dataclass(frozen=True)
class RunCompletion:
    state: str = "completed"
    instances_completed: int = 0
    instances_partial: int = 0
    instances_failed: int = 0
    instances_interrupted: int = 0
    instances_timed_out: int = 0
    trace_artifact_total_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.state not in {"completed", "partial", "failed", "interrupted"}:
            raise ValueError(f"unsupported run state: {self.state}")
        values = (
            self.instances_completed,
            self.instances_partial,
            self.instances_failed,
            self.instances_interrupted,
            self.instances_timed_out,
        )
        if any(value < 0 for value in values):
            raise ValueError("instance counts cannot be negative")
        if self.trace_artifact_total_bytes is not None and self.trace_artifact_total_bytes < 0:
            raise ValueError("trace_artifact_total_bytes cannot be negative")


def _resolved_instance_ids_sha256(instance_ids: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for instance_id in sorted(instance_ids):
        digest.update(instance_id.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _git_metadata(repo_path: Path) -> tuple[str | None, bool | None]:
    try:
        import git

        repo = git.Repo(repo_path, search_parent_directories=True)
        return repo.head.commit.hexsha, repo.is_dirty(untracked_files=True)
    except Exception:
        return None, None


def collect_software_metadata(repo_path: Path | None = None) -> dict[str, object]:
    revision, dirty = _git_metadata(repo_path or Path.cwd())
    return {
        "explainbench_git_revision": revision,
        "explainbench_git_dirty": dirty,
        "python_version": platform.python_version(),
        "swebench_version": _package_version("swebench"),
        "docker_sdk_version": _package_version("docker"),
    }


def collect_docker_metadata() -> tuple[dict[str, str], list[dict[str, str | None]]]:
    try:
        import docker

        client = docker.from_env()
        try:
            info = client.info()
            version = client.version()
        finally:
            client.close()
        cgroup_version = str(info.get("CgroupVersion", "unknown"))
        if cgroup_version not in {"1", "2"}:
            cgroup_version = "unknown"
        return (
            {
                "server_version": str(version.get("Version", "unknown")),
                "api_version": str(version.get("ApiVersion", "unknown")),
                "storage_driver": str(info.get("Driver", "unknown")),
                "data_root": str(info.get("DockerRootDir", "unknown")),
                "cgroup_version": cgroup_version,
            },
            [],
        )
    except Exception as error:
        return (
            {
                "server_version": "unknown",
                "api_version": "unknown",
                "storage_driver": "unknown",
                "data_root": "unknown",
                "cgroup_version": "unknown",
            },
            [
                {
                    "source": "measurement",
                    "code": "docker_metadata_unavailable",
                    "message": _bounded_message(error),
                    "exception_type": error.__class__.__name__,
                }
            ],
        )


def collect_host_metadata(docker_metadata: dict[str, str]) -> dict[str, object]:
    memory_total = 0
    swap_total = 0
    try:
        meminfo = _parse_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))
        memory_total = meminfo["MemTotal"]
        swap_total = meminfo["SwapTotal"]
    except (OSError, ValueError):
        pass
    return {
        "operating_system": _read_os_release(),
        "kernel_version": platform.release(),
        "architecture": platform.machine() or "unknown",
        "cpu_model": _read_cpu_model(),
        "logical_cpu_count": os.cpu_count() or 1,
        "memory_total_bytes": memory_total,
        "swap_total_bytes": swap_total,
        "storage_type": None,
        "docker_server_version": docker_metadata["server_version"],
        "docker_api_version": docker_metadata["api_version"],
        "docker_storage_driver": docker_metadata["storage_driver"],
        "docker_data_root": docker_metadata["data_root"],
        "cgroup_version": docker_metadata["cgroup_version"],
    }


def _atomic_write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(data, temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


class RunResourceMonitor:
    def __init__(
        self,
        config: RunResourceConfig,
        output_path: str | os.PathLike[str],
        trace_output_path: str | os.PathLike[str],
        *,
        interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
        container_aggregate_provider: Callable[[], ContainerAggregate] | None = None,
        sample_source: HostSampleSource | None = None,
        software_metadata: dict[str, object] | None = None,
        host_metadata: dict[str, object] | None = None,
        docker_metadata: dict[str, str] | None = None,
        docker_metadata_errors: Sequence[dict[str, str | None]] = (),
        utc_now: Callable[[], datetime] = _utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.config = config
        self.output_path = Path(output_path)
        self._utc_now = utc_now
        self._monotonic_ns = monotonic_ns

        metadata_errors: list[dict[str, str | None]] = []
        if docker_metadata is None:
            docker_metadata, metadata_errors = collect_docker_metadata()
        self._metadata_errors = [*metadata_errors, *docker_metadata_errors]
        self.software_metadata = software_metadata or collect_software_metadata()
        self.host_metadata = host_metadata or collect_host_metadata(docker_metadata)

        source = sample_source or LinuxHostSampleSource(
            trace_output_path,
            docker_metadata.get("data_root"),
            container_aggregate_provider=container_aggregate_provider,
            utc_now=utc_now,
            monotonic_ns=monotonic_ns,
        )
        self.sampler = HostResourceSampler(
            source,
            interval_seconds=interval_seconds,
        )
        self._started_at: datetime | None = None
        self._started_monotonic_ns: int | None = None
        self._record: dict[str, object] | None = None
        self._context_completion: RunCompletion | None = None

    def start(self) -> RunResourceMonitor:
        if self._started_at is not None:
            raise RuntimeError("run resource monitor has already been started")
        self._started_at = self._utc_now()
        self._started_monotonic_ns = self._monotonic_ns()
        self.sampler.start()
        return self

    def set_context_completion(self, completion: RunCompletion) -> None:
        self._context_completion = completion

    def stop(self, completion: RunCompletion | None = None) -> dict[str, object]:
        if self._record is not None:
            return self._record
        if self._started_at is None or self._started_monotonic_ns is None:
            raise RuntimeError("run resource monitor has not been started")

        self.sampler.stop()
        ended_at = self._utc_now()
        ended_monotonic_ns = self._monotonic_ns()
        final = completion or self._context_completion or RunCompletion()
        sampler_snapshot = self.sampler.snapshot()
        record = self._build_record(
            final,
            ended_at,
            max(0.0, (ended_monotonic_ns - self._started_monotonic_ns) / 1e9),
            sampler_snapshot,
        )
        _atomic_write_json(self.output_path, record)
        self._record = record
        return record

    def _build_record(
        self,
        completion: RunCompletion,
        ended_at: datetime,
        wall_time_seconds: float,
        sampler_snapshot: dict[str, object],
    ) -> dict[str, object]:
        metrics = dict(sampler_snapshot["metrics"])
        metrics["trace_artifact_total_bytes"] = completion.trace_artifact_total_bytes
        metrics.update(
            {
                "instances_completed": completion.instances_completed,
                "instances_partial": completion.instances_partial,
                "instances_failed": completion.instances_failed,
                "instances_interrupted": completion.instances_interrupted,
                "instances_timed_out": completion.instances_timed_out,
                "throughput_completed_per_hour": (
                    3600.0 * completion.instances_completed / wall_time_seconds
                    if wall_time_seconds > 0
                    else None
                ),
            }
        )

        filesystems = list(sampler_snapshot["filesystems"])
        missing_metrics = self._missing_metrics(metrics, filesystems)
        measurement_state = self._measurement_state(metrics, filesystems)
        errors = [*self._metadata_errors, *sampler_snapshot["errors"]]

        return {
            "schema_version": SCHEMA_VERSION,
            "record_type": "run",
            "generated_at": _format_timestamp(ended_at),
            "run": {
                "run_id": self.config.run_id,
                "agent": self.config.agent,
                "instance_selection": list(self.config.instance_selection),
                "resolved_instance_count": len(self.config.resolved_instance_ids),
                "resolved_instance_ids_sha256": _resolved_instance_ids_sha256(
                    self.config.resolved_instance_ids
                ),
                "max_workers": self.config.max_workers,
                "timeout_seconds": self.config.timeout_seconds,
                "cache_state": self.config.cache_state,
                "started_at": _format_timestamp(self._started_at),
                "ended_at": _format_timestamp(ended_at),
                "wall_time_seconds": wall_time_seconds,
                "state": completion.state,
            },
            "software": self.software_metadata,
            "host": self.host_metadata,
            "sampling": sampler_snapshot["sampling"],
            "measurement": {
                "state": measurement_state,
                "missing_metrics": missing_metrics,
            },
            "summary": metrics,
            "filesystems": filesystems,
            "errors": errors,
        }

    @staticmethod
    def _missing_metrics(
        metrics: dict[str, object], filesystems: list[dict[str, object]]
    ) -> list[str]:
        names = {
            "memory_used_sampled_peak_bytes": "host.memory_used_sampled_peak_bytes",
            "memory_available_sampled_min_bytes": (
                "host.memory_available_sampled_min_bytes"
            ),
            "swap_used_sampled_peak_bytes": "host.swap_used_sampled_peak_bytes",
            "cpu_percent_mean": "host.cpu_percent_mean",
            "cpu_percent_peak": "host.cpu_percent_peak",
            "load1_sampled_peak": "host.load1_sampled_peak",
            "active_trace_containers_peak": "containers.active_count",
            "aggregate_container_working_set_sampled_peak_bytes": (
                "containers.aggregate_working_set_bytes"
            ),
            "trace_artifact_total_bytes": "trace_artifact_total_bytes",
        }
        missing = [path for name, path in names.items() if metrics.get(name) is None]
        for filesystem in filesystems:
            if filesystem.get("available_min_bytes") is None:
                missing.append(f"filesystem.{filesystem['role']}.available_min_bytes")
        return sorted(missing)

    @staticmethod
    def _measurement_state(
        metrics: dict[str, object], filesystems: list[dict[str, object]]
    ) -> str:
        core_values = [
            metrics.get("memory_used_sampled_peak_bytes"),
            metrics.get("memory_available_sampled_min_bytes"),
            metrics.get("trace_artifact_total_bytes"),
        ]
        core_values.extend(
            filesystem.get("available_min_bytes")
            for filesystem in filesystems
            if filesystem.get("role") == "trace_output"
        )
        available_core = sum(value is not None for value in core_values)
        if available_core == 0:
            return "unavailable"
        if RunResourceMonitor._missing_metrics(metrics, filesystems):
            return "partial"
        return "complete"

    def __enter__(self) -> RunResourceMonitor:
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is not None and issubclass(
            exc_type, (KeyboardInterrupt, SystemExit)
        ):
            completion = RunCompletion(state="interrupted")
        elif exc_type is not None:
            completion = RunCompletion(state="failed")
        elif self._context_completion is not None:
            completion = self._context_completion
        else:
            completion = RunCompletion(state="completed")

        try:
            self.stop(completion)
        except Exception:
            if exc_type is None:
                raise
        return False
