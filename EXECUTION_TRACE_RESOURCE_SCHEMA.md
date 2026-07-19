# `execution.trace` Resource Metrics Schema v1

This document is the Phase 1 specification for the resource measurement work
tracked in [`EXECUTION_TRACE_RESOURCE_PLAN.md`](./EXECUTION_TRACE_RESOURCE_PLAN.md).
The machine-readable schema is
[`execution/resource_usage.schema.json`](./execution/resource_usage.schema.json).

## 1. Compatibility and Conventions

- `schema_version` is the integer `1` for both run and instance records.
- JSON property names include their units: `_bytes`, `_ns`, or `_seconds`.
- Byte values are binary byte counts, not displayed KiB/MiB/GiB values.
- CPU usage counters are nanoseconds of container CPU time. Divide by `1e9` to
  obtain CPU-seconds.
- Percent values use `100` for one fully utilized logical CPU. A container
  using four CPUs fully may therefore report `400` percent.
- Durations use `time.monotonic_ns()` internally and are serialized in seconds.
- Timestamps are UTC RFC 3339 strings, normally with a `Z` suffix.
- A missing or unsupported numeric measurement is `null`, never zero.
- Zero means the source was available and the observed value was actually zero.
- Counters that decrease, reset, or come from different container identities
  produce `null` deltas and a measurement error.
- Negative working-set estimates are clamped to zero.
- Aggregations never silently omit unavailable data. The corresponding
  `measurement.missing_metrics` entry identifies the omission.
- `resolved_instance_ids_sha256` is the lowercase SHA-256 hex digest produced
  by sorting resolved instance IDs, encoding each as UTF-8, and appending one
  NUL byte after every encoded ID before hashing.

The schema deliberately separates workload outcome from measurement status. A
trace can complete even if Docker statistics are unavailable, and monitoring
can complete even when the trace times out.

## 2. Record Locations

Run summary:

```text
logs/run_evaluation/trace.<agent>.<uid>/resource_usage.run.json
```

Instance summary:

```text
logs/run_evaluation/trace.<agent>.<uid>/<agent>/<instance_id>/resource_usage.json
```

Files are written atomically by creating a temporary sibling and replacing the
destination. The final write occurs in a `finally` path. Raw time-series samples
are not retained in schema v1 by default; the samplers aggregate them online.

## 3. Phase Boundaries

The pinned execution dependency is SWE-bench 4.1.0. Phase names describe the
actual current execution flow rather than implying that only traced Python code
runs inside a phase.

| Phase | Start | End | Resource coverage |
|---|---|---|---|
| `container_setup` | Immediately before `build_container` | Container has started | Host metrics and wall time; container counters may be unavailable before start |
| `tracer_archive_copy` | Before `container.put_archive` | Archive copy returns | Host and container metrics where available |
| `patch_prepare_apply` | Before prediction patch creation/copy | Patch is applied and pre-run diff is captured | Host and container |
| `buggy_prepare` | Before generating buggy `eval.sh` | Script is copied to the container | Host and container |
| `buggy_exec` | Immediately before `exec_run_with_timeout` | Call returns or raises | Host and container |
| `buggy_copy_out` | Before `copy_directory_from_docker` | Copy returns or raises | Host and container |
| `patched_prepare` | Before generating patched `eval.sh` | Script is copied to the container | Host and container |
| `patched_exec` | Immediately before patched `exec_run_with_timeout` | Call returns or raises | Host and container |
| `patched_copy_out` | Before patched `copy_directory_from_docker` | Copy returns or raises | Host and container |
| `grading` | After patched output path is selected | Report writing completes or raises | Host and container |
| `cleanup` | Immediately before cleanup | Cleanup returns or raises | Host metrics; final container counters must be captured before removal |

The `buggy_exec` and `patched_exec` scripts include environment activation,
tracer installation, selected test execution, `git clean`, and `/tmp` cleanup.
They are therefore named `*_exec`, not `*_test`. Splitting those commands would
require intrusive instrumentation inside each project-specific evaluation
script and is not part of schema v1.

A phase that was never reached has `state: "skipped"`, null timestamps and
metrics, and `sample_count: 0`. A started phase is always finalized as
`completed`, `timed_out`, `failed`, or `interrupted`.

## 4. Sampling Semantics

The default interval is exactly `1.0` second for host and container sampling.
Phase transitions also request a Docker one-shot snapshot so short phases have
boundary data without waiting for two Docker statistics cycles. The Docker API
must be called with `stream=false` and, when API version 1.41 or newer is
available, `one-shot=true`.

Every record includes:

- Attempted sample count
- Successful sample count
- Failed sample count
- First and last successful sample timestamps

A sampling error does not stop tracing. It changes measurement state to
`partial` unless all core measurements are unavailable, in which case the state
is `unavailable`.

### Measurement completeness

Core run measurements are wall time, host memory, trace-output filesystem free
space, completed/failed counts, and trace artifact bytes.

Core instance measurements are wall time, container CPU, sampled container
memory, and trace artifact bytes.

- `complete`: all core metrics are present.
- `partial`: at least one core metric is present and at least one requested
  metric is missing.
- `unavailable`: none of the core resource metrics could be collected. Workload
  status and wall-clock timestamps should still be recorded where possible.

## 5. Metric Sources and Formulas

### 5.1 Host CPU

Source: consecutive `/proc/stat` aggregate `cpu` rows.

```text
idle_delta = delta(idle + iowait)
total_delta = delta(user + nice + system + idle + iowait + irq + softirq + steal)
host_cpu_percent = 100 * (total_delta - idle_delta) / total_delta
```

The value is null if `total_delta <= 0` or counters reset. Mean is weighted by
the sampled time interval; peak is the maximum valid interval value.

### 5.2 Host memory and swap

Source: `/proc/meminfo`.

```text
memory_used_bytes = MemTotal - MemAvailable
swap_used_bytes = SwapTotal - SwapFree
```

`MemAvailable`, rather than `MemFree`, represents memory available without
substantial swapping. Run records retain peak used memory, minimum available
memory, and peak swap use.

### 5.3 Host load

Source: the one-minute load value in `/proc/loadavg`. The run record retains
the sampled peak as `load1_sampled_peak`.

### 5.4 Filesystem capacity

Source: `os.statvfs()` for the trace output path and Docker data root.

```text
total_bytes = f_blocks * f_frsize
available_bytes = f_bavail * f_frsize
```

`f_bavail` is used because it reflects space available to the tracing process,
excluding blocks reserved from unprivileged users. Start, sampled minimum, and
end values are retained. If both roles reside on the same filesystem, both role
records may contain the same capacity values; they must not be added together.

Docker's data root comes from daemon info. If it cannot be stat'ed from the
client namespace, Docker-root filesystem values are null and named in
`missing_metrics`. Filesystem free-space minima are the authoritative capacity
signal; daemon-wide `docker system df` values may be collected later as
diagnostic metadata but are not used as the v1 requirement calculation because
unrelated Docker activity can contaminate them.

### 5.5 Container CPU time

Source: `cpu_stats.cpu_usage.total_usage` from Docker statistics. Docker reports
this cumulative counter in nanoseconds.

```text
cpu_usage_ns = end_total_usage - start_total_usage
```

Phase values use boundary snapshots. The container total uses the first and
last valid snapshots for the same container ID.

### 5.6 Container CPU percentage

Source: consecutive Docker statistics samples.

```text
container_delta = delta(cpu_stats.cpu_usage.total_usage)
system_delta = delta(cpu_stats.system_cpu_usage)
online_cpus = cpu_stats.online_cpus
              or len(cpu_stats.cpu_usage.percpu_usage)
container_cpu_percent = 100 * container_delta / system_delta * online_cpus
```

The value is null if either delta is nonpositive or the CPU count is missing.
Mean is time-weighted. CPU time is the primary consumption measurement; CPU
percentage is retained to understand concurrency and saturation.

### 5.7 Container raw memory

Source: `memory_stats.usage`. This includes reclaimable page cache and is kept
for reproducibility with Docker's raw counter.

The sampled peak is the maximum valid value assigned to the phase. An exact
container-lifetime peak is stored separately when available:

- cgroup v1: `memory_stats.max_usage`, source `docker_max_usage`
- cgroup v2: `memory.peak`, source `cgroup_memory_peak`
- otherwise: null; the sampled peak remains available

An exact lifetime peak must not be reported as a phase-specific peak because it
cannot generally be reset safely at each phase boundary.

### 5.8 Container working-set memory

Source: Docker memory statistics.

```text
cgroup v1 cache = memory_stats.stats.total_inactive_file
                  fallback memory_stats.stats.inactive_file
cgroup v2 cache = memory_stats.stats.inactive_file
working_set_bytes = max(0, memory_stats.usage - cache)
```

If the applicable inactive-file field is absent, the working set is null; raw
memory usage remains valid. Both raw and working-set peaks are published so
results remain interpretable across Docker/cgroup versions.

### 5.9 Block I/O

Source: `blkio_stats.io_service_bytes_recursive`.

For each snapshot, sum `value` across devices only for entries whose lowercase
`op` is exactly `read` or `write`. Do not add `total`, `sync`, or `async` rows.
Phase bytes are end minus start. Missing arrays produce null, while an available
empty array represents zero.

Block I/O measures device traffic, not persistent disk footprint. Hardware disk
requirements use filesystem minima and trace artifact sizes instead.

### 5.10 Process count

Source: `pids_stats.current`. `pids_sampled_peak` is the maximum valid sample.
This field is optional for capacity guidance and may be null on unsupported
platforms.

### 5.11 Container limits and OOM evidence

Configured limits come from container inspection, not from
`memory_stats.limit`, because an unlimited container may report host memory as
its apparent limit.

- `HostConfig.Memory == 0` becomes `memory_limit_bytes: null`.
- `HostConfig.NanoCpus == 0` becomes `nano_cpus: null`.
- An absent/unlimited PID limit becomes `pids_limit: null`.

Before cleanup, inspect the container state and available cgroup OOM counters.
Set `oom_killed` to true only with affirmative evidence, false only when the
source was successfully checked, and null when it could not be determined. A
timeout near a memory peak is not automatically classified as OOM.

### 5.12 Trace artifacts

Source: the copied buggy or patched trace directory.

- `file_count`: number of regular files below the directory
- `total_bytes`: sum of regular-file `st_size`
- `largest_file_bytes`: maximum regular-file `st_size`, or zero for no files
- `event_count`: save-time tracer counter when implemented, otherwise null

Artifact state is `complete`, `partial`, or `missing`. File enumeration occurs
after copy-out; JSONL content is not reread during the timed run.

### 5.13 Throughput

```text
throughput_completed_per_hour = 3600 * instances_completed / run_wall_time_seconds
```

Only workload outcome `completed` contributes to the numerator. Partial,
failed, interrupted, or timed-out instances remain separately counted.

## 6. Workload Outcomes and Errors

Workload `state` values:

- `completed`: the tracing workflow reached normal evaluation completion.
- `partial`: at least one useful trace phase/artifact completed, but the workflow
  did not finish.
- `failed`: no usable tracing result was produced.
- `interrupted`: an external signal or cancellation stopped the workflow.

`failure_kind` is null on success and otherwise one of:

```text
timeout
oom_killed
patch_error
docker_error
tracer_error
evaluation_error
cancelled
unknown_error
```

An expected failing test is not itself a tracing failure. `evaluation_completed`
and `resolved` preserve SWE-bench's evaluation result separately.

Errors identify `source` as `workload` or `measurement`. Error messages must be
bounded summaries and must not contain environment variables, credentials, or
unbounded command output.

## 7. Cache-State Semantics

Cache state is benchmark metadata, not an unreliable automatic inference:

- `cold`: required instance/environment images were absent before the run.
- `warm`: all required images were present and no rebuild was requested.
- `mixed`: some required images were present.
- `unknown`: the benchmark operator did not establish the state.

The implementation should default to `unknown`. Capacity reports may label a
run cold/warm only when the benchmark procedure explicitly establishes it.

## 8. Portability Fallbacks

| Metric | Primary | Fallback | If neither works |
|---|---|---|---|
| Host CPU | `/proc/stat` | None in schema v1 | null |
| Host memory/swap | `/proc/meminfo` | None in schema v1 | null |
| Filesystem space | `os.statvfs` | Same-filesystem accessible ancestor | null |
| Container CPU time | Docker `total_usage` | None | null |
| Container raw memory | Docker `memory_stats.usage` | None | null |
| Container working set, v1 | `total_inactive_file` | `inactive_file` | null |
| Container working set, v2 | `inactive_file` | None | null |
| Lifetime memory peak, v1 | Docker `max_usage` | sampled raw peak | exact field null |
| Lifetime memory peak, v2 | cgroup `memory.peak` | sampled raw peak | exact field null |
| Block I/O | Docker recursive service bytes | None | null or zero only if array is present and empty |
| PIDs | Docker `pids_stats.current` | None | null |
| OOM evidence | Container state/cgroup counter | None | null |

Linux is the supported measurement platform for schema v1. If tracing itself
runs on a non-Linux Docker host, workload execution may continue, but Linux host
metrics are marked unavailable rather than approximated with different
semantics.

## 9. Examples

Examples omit no required schema fields, though several values are illustrative.

### 9.1 Successful instance

```json
{
  "schema_version": 1,
  "record_type": "instance",
  "generated_at": "2026-07-18T03:20:00Z",
  "run_id": "trace.gold.1000",
  "agent": "gold",
  "instance_id": "django__django-12345",
  "container": {
    "id": "4b2c6f",
    "image": "swebench/sweb.eval.x86_64.django_12345:latest",
    "memory_limit_bytes": null,
    "nano_cpus": null,
    "pids_limit": null,
    "lifetime_peak_memory_bytes": 1254096896,
    "lifetime_peak_memory_source": "docker_max_usage",
    "oom_killed": false
  },
  "started_at": "2026-07-18T03:18:36Z",
  "ended_at": "2026-07-18T03:20:00Z",
  "wall_time_seconds": 84.0,
  "outcome": {
    "state": "completed",
    "failure_kind": null,
    "failed_phase": null,
    "evaluation_completed": true,
    "resolved": true
  },
  "measurement": {
    "state": "complete",
    "missing_metrics": []
  },
  "sampling": {
    "interval_seconds": 1.0,
    "attempted_samples": 84,
    "successful_samples": 84,
    "failed_samples": 0,
    "first_sample_at": "2026-07-18T03:18:37Z",
    "last_sample_at": "2026-07-18T03:20:00Z"
  },
  "container_metrics": {
    "wall_time_seconds": 80.5,
    "cpu_usage_ns": 58900000000,
    "cpu_percent_mean": 73.2,
    "cpu_percent_peak": 196.4,
    "memory_usage_sampled_peak_bytes": 1249902592,
    "memory_working_set_sampled_peak_bytes": 1182793728,
    "block_io_read_bytes": 10485760,
    "block_io_write_bytes": 419430400,
    "pids_sampled_peak": 37,
    "sample_count": 81
  },
  "phases": {
    "buggy_exec": {
      "state": "completed",
      "started_at": "2026-07-18T03:18:42Z",
      "ended_at": "2026-07-18T03:19:14Z",
      "metrics": {
        "wall_time_seconds": 32.0,
        "cpu_usage_ns": 24700000000,
        "cpu_percent_mean": 76.1,
        "cpu_percent_peak": 187.0,
        "memory_usage_sampled_peak_bytes": 912261120,
        "memory_working_set_sampled_peak_bytes": 880803840,
        "block_io_read_bytes": 5242880,
        "block_io_write_bytes": 188743680,
        "pids_sampled_peak": 31,
        "sample_count": 32
      }
    },
    "patched_exec": {
      "state": "completed",
      "started_at": "2026-07-18T03:19:21Z",
      "ended_at": "2026-07-18T03:19:57Z",
      "metrics": {
        "wall_time_seconds": 36.0,
        "cpu_usage_ns": 28600000000,
        "cpu_percent_mean": 78.3,
        "cpu_percent_peak": 196.4,
        "memory_usage_sampled_peak_bytes": 1249902592,
        "memory_working_set_sampled_peak_bytes": 1182793728,
        "block_io_read_bytes": 2097152,
        "block_io_write_bytes": 209715200,
        "pids_sampled_peak": 37,
        "sample_count": 36
      }
    }
  },
  "artifacts": {
    "buggy": {
      "state": "complete",
      "file_count": 2,
      "total_bytes": 183345221,
      "largest_file_bytes": 170002100,
      "event_count": 97230
    },
    "patched": {
      "state": "complete",
      "file_count": 2,
      "total_bytes": 216782833,
      "largest_file_bytes": 204441002,
      "event_count": 110421
    }
  },
  "errors": []
}
```

### 9.2 Timeout after a usable buggy trace

This is a partial workload result, while measurement itself is complete.

```json
{
  "schema_version": 1,
  "record_type": "instance",
  "generated_at": "2026-07-18T04:10:00Z",
  "run_id": "trace.gold.1000",
  "agent": "gold",
  "instance_id": "sympy__sympy-99999",
  "container": {
    "id": "8ce913",
    "image": "swebench/sweb.eval.x86_64.sympy_99999:latest",
    "memory_limit_bytes": null,
    "nano_cpus": null,
    "pids_limit": null,
    "lifetime_peak_memory_bytes": 7516192768,
    "lifetime_peak_memory_source": "docker_max_usage",
    "oom_killed": false
  },
  "started_at": "2026-07-18T03:00:00Z",
  "ended_at": "2026-07-18T04:10:00Z",
  "wall_time_seconds": 4200.0,
  "outcome": {
    "state": "partial",
    "failure_kind": "timeout",
    "failed_phase": "patched_exec",
    "evaluation_completed": false,
    "resolved": null
  },
  "measurement": {
    "state": "complete",
    "missing_metrics": []
  },
  "sampling": {
    "interval_seconds": 1.0,
    "attempted_samples": 4200,
    "successful_samples": 4199,
    "failed_samples": 1,
    "first_sample_at": "2026-07-18T03:00:01Z",
    "last_sample_at": "2026-07-18T04:10:00Z"
  },
  "container_metrics": {
    "wall_time_seconds": 4197.0,
    "cpu_usage_ns": 8012000000000,
    "cpu_percent_mean": 190.8,
    "cpu_percent_peak": 403.2,
    "memory_usage_sampled_peak_bytes": 7507804160,
    "memory_working_set_sampled_peak_bytes": 7193231360,
    "block_io_read_bytes": 734003200,
    "block_io_write_bytes": 12884901888,
    "pids_sampled_peak": 82,
    "sample_count": 4199
  },
  "phases": {
    "buggy_exec": {
      "state": "completed",
      "started_at": "2026-07-18T03:00:08Z",
      "ended_at": "2026-07-18T03:04:08Z",
      "metrics": {
        "wall_time_seconds": 240.0,
        "cpu_usage_ns": 415000000000,
        "cpu_percent_mean": 172.9,
        "cpu_percent_peak": 390.0,
        "memory_usage_sampled_peak_bytes": 3221225472,
        "memory_working_set_sampled_peak_bytes": 3087007744,
        "block_io_read_bytes": 125829120,
        "block_io_write_bytes": 2147483648,
        "pids_sampled_peak": 61,
        "sample_count": 240
      }
    },
    "patched_exec": {
      "state": "timed_out",
      "started_at": "2026-07-18T03:10:00Z",
      "ended_at": "2026-07-18T04:10:00Z",
      "metrics": {
        "wall_time_seconds": 3600.0,
        "cpu_usage_ns": 7020000000000,
        "cpu_percent_mean": 195.0,
        "cpu_percent_peak": 403.2,
        "memory_usage_sampled_peak_bytes": 7507804160,
        "memory_working_set_sampled_peak_bytes": 7193231360,
        "block_io_read_bytes": 536870912,
        "block_io_write_bytes": 9663676416,
        "pids_sampled_peak": 82,
        "sample_count": 3600
      }
    }
  },
  "artifacts": {
    "buggy": {
      "state": "complete",
      "file_count": 1,
      "total_bytes": 1717986918,
      "largest_file_bytes": 1717986918,
      "event_count": null
    },
    "patched": {
      "state": "missing",
      "file_count": 0,
      "total_bytes": 0,
      "largest_file_bytes": 0,
      "event_count": null
    }
  },
  "errors": [
    {
      "source": "workload",
      "code": "exec_timeout",
      "message": "Patched evaluation exceeded the configured timeout.",
      "exception_type": "EvaluationError"
    }
  ]
}
```

### 9.3 Completed workload with partial measurement

Only the fields that differ materially from the successful example are shown
here; a stored record still contains every required field.

```json
{
  "outcome": {
    "state": "completed",
    "failure_kind": null,
    "failed_phase": null,
    "evaluation_completed": true,
    "resolved": false
  },
  "measurement": {
    "state": "partial",
    "missing_metrics": [
      "container.cpu_usage_ns",
      "container.block_io_read_bytes",
      "container.block_io_write_bytes"
    ]
  },
  "container_metrics": {
    "wall_time_seconds": 80.5,
    "cpu_usage_ns": null,
    "cpu_percent_mean": null,
    "cpu_percent_peak": null,
    "memory_usage_sampled_peak_bytes": 1249902592,
    "memory_working_set_sampled_peak_bytes": 1182793728,
    "block_io_read_bytes": null,
    "block_io_write_bytes": null,
    "pids_sampled_peak": 37,
    "sample_count": 79
  },
  "errors": [
    {
      "source": "measurement",
      "code": "docker_stats_fields_missing",
      "message": "Docker statistics did not expose CPU or block-I/O counters.",
      "exception_type": null
    }
  ]
}
```

### 9.4 Successful run summary

```json
{
  "schema_version": 1,
  "record_type": "run",
  "generated_at": "2026-07-18T06:00:00Z",
  "run": {
    "run_id": "trace.gold.1000",
    "agent": "gold",
    "instance_selection": ["django"],
    "resolved_instance_count": 25,
    "resolved_instance_ids_sha256": "91dbb8809f5d7ee1",
    "max_workers": 4,
    "timeout_seconds": 21600,
    "cache_state": "warm",
    "started_at": "2026-07-18T03:00:00Z",
    "ended_at": "2026-07-18T06:00:00Z",
    "wall_time_seconds": 10800.0,
    "state": "completed"
  },
  "software": {
    "explainbench_git_revision": "3aa3e7b",
    "explainbench_git_dirty": true,
    "python_version": "3.12.0",
    "swebench_version": "4.1.0",
    "docker_sdk_version": "7.1.0"
  },
  "host": {
    "operating_system": "Ubuntu 20.04.6 LTS",
    "kernel_version": "5.15.0-139-generic",
    "architecture": "x86_64",
    "cpu_model": "Example CPU",
    "logical_cpu_count": 32,
    "memory_total_bytes": 137438953472,
    "swap_total_bytes": 0,
    "storage_type": "NVMe SSD",
    "docker_server_version": "28.0.1",
    "docker_api_version": "1.48",
    "docker_storage_driver": "overlay2",
    "docker_data_root": "/var/lib/docker",
    "cgroup_version": "1"
  },
  "sampling": {
    "interval_seconds": 1.0,
    "attempted_samples": 10800,
    "successful_samples": 10799,
    "failed_samples": 1,
    "first_sample_at": "2026-07-18T03:00:01Z",
    "last_sample_at": "2026-07-18T06:00:00Z"
  },
  "measurement": {
    "state": "complete",
    "missing_metrics": []
  },
  "summary": {
    "memory_used_sampled_peak_bytes": 68719476736,
    "memory_available_sampled_min_bytes": 68719476736,
    "swap_used_sampled_peak_bytes": 0,
    "cpu_percent_mean": 61.0,
    "cpu_percent_peak": 98.0,
    "load1_sampled_peak": 20.5,
    "active_trace_containers_peak": 4,
    "aggregate_container_working_set_sampled_peak_bytes": 51539607552,
    "trace_artifact_total_bytes": 32212254720,
    "instances_completed": 23,
    "instances_partial": 1,
    "instances_failed": 1,
    "instances_interrupted": 0,
    "instances_timed_out": 1,
    "throughput_completed_per_hour": 7.67
  },
  "filesystems": [
    {
      "role": "trace_output",
      "path": "/workspace/logs/run_evaluation",
      "total_bytes": 1099511627776,
      "available_start_bytes": 824633720832,
      "available_min_bytes": 786442665984,
      "available_end_bytes": 791648371712
    },
    {
      "role": "docker_data_root",
      "path": "/var/lib/docker",
      "total_bytes": 2199023255552,
      "available_start_bytes": 1649267441664,
      "available_min_bytes": 1580547964928,
      "available_end_bytes": 1597727834112
    }
  ],
  "errors": []
}
```

## 10. Phase 1 Decisions

1. Use schema version 1 and explicit unit suffixes.
2. Default to one-second sampling plus one-shot phase-boundary snapshots.
3. Aggregate samples online; do not retain raw time series by default.
4. Separate workload outcome from measurement completeness.
5. Treat filesystem free-space minima and actual trace bytes as disk-capacity
   evidence; do not use block I/O as a disk-footprint estimate.
6. Retain raw and working-set memory; use exact lifetime peak only when the
   platform exposes it.
7. Require affirmative evidence before labeling a failure as OOM.
8. Treat cache state as controlled benchmark metadata rather than inference.
9. Support Linux host measurements in schema v1 and represent unsupported
   fields as null.
