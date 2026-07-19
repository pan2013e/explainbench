# `execution.trace` Resource Measurement Plan

## Purpose

Measure the CPU, memory, disk, and runtime consumption of `execution.trace` so
the ExplainBench release can publish a transparent observed resource profile
and conservative operating guidance without claiming an unvalidated minimum
hardware configuration.

This document is also the progress tracker for the work. It should be updated
whenever a phase starts, finishes, or changes scope.

## Scope

In scope:

- `python -m execution.trace`
- Host-level resource consumption during a trace run
- Per-instance SWE-bench container consumption
- Buggy and patched traced-test phases
- Copying and storing generated traces
- Warm-cache, single-worker capacity measurements
- Aggregation of raw measurements into release-facing resource guidance

Out of scope for this work:

- `dataset.extract_ground_truths.effect.build_step1` and later build steps
- LLM inference resource consumption
- Property-based test generation
- Optimization of the tracer itself, unless measurement reveals a blocker
- Cold-cache image-footprint measurement and destructive cache clearing
- Empirical multi-worker capacity claims, until concurrency testing is resumed

## Status

Status values:

- `NOT STARTED`: No implementation work has begun.
- `IN PROGRESS`: This is the current active phase.
- `BLOCKED`: Progress requires a decision or external dependency.
- `COMPLETE`: Acceptance criteria for the phase have been met.

Current focus: Phases 0 through 9 are complete for the revised single-worker
release scope. Concurrency and cold-cache characterization remain explicitly
deferred future work.

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Document scope and staged plan | COMPLETE |
| 1 | Define metrics schema and measurement semantics | COMPLETE |
| 2 | Implement run-level host sampler | COMPLETE |
| 3 | Implement per-container Docker sampler | COMPLETE |
| 4 | Integrate phase tracking into `execution.trace` | COMPLETE |
| 5 | Record trace artifact statistics | COMPLETE |
| 6 | Add automated tests and failure-path coverage | COMPLETE |
| 7 | Run and validate a one-instance pilot | COMPLETE |
| 8 | Run and analyze the single-worker capacity benchmark | COMPLETE |
| 9 | Publish the observed profile and operating guidance | COMPLETE |

## Guiding Principles

1. Measure capacity, not only code performance. Report observed demand on the
   tested host without presenting it as a validated minimum configuration.
2. Preserve attribution. Run-level metrics describe observed host demand,
   while per-instance and per-phase metrics explain its sources.
3. Preserve failure data. Timeouts, OOMs, exceptions, and partial traces must
   still produce a resource record.
4. Keep measurement overhead low and quantify it during the pilot.
5. Do not publish a resource number without its workload, concurrency, cache
   state, host configuration, and interpretation limits.
6. Store raw measurements so recommendations can be recalculated later.

## Workload Model

The unit of work is one `(agent, instance_id)` pair. A trace run may process
many units concurrently according to `--max_workers`.

Each unit should be divided into these phases where the current execution flow
allows reliable boundaries:

1. Container setup and tracer installation
2. Patch application and evaluation preparation
3. Buggy traced-test execution
4. Buggy trace copy-out
5. Patched traced-test execution
6. Patched trace copy-out
7. Finalization and cleanup

Wall-clock time should be measured with a monotonic clock. Container CPU and
I/O should be calculated from cumulative counter differences. Memory peaks
should be obtained from Docker/cgroup peak counters where available and from
periodic sampling as a portable fallback.

## Metrics

### Run metadata

- Schema version
- Run ID and timestamp
- ExplainBench Git revision and dirty-worktree indicator
- Agent ID and selected instance IDs
- `--max_workers` and timeout
- Sampling interval
- Cold-cache or warm-cache classification
- Host operating system, kernel, and cgroup version
- Docker client/server versions and Docker data-root filesystem
- CPU model, logical CPU count, total RAM, swap, and storage type when known

### Host-level metrics

- Total run wall time
- Peak used memory and minimum available memory
- Peak swap usage
- CPU utilization and load
- Peak number of active tracing containers
- Peak aggregate container working set
- Minimum free space on the trace-output filesystem
- Minimum free space on Docker's data-root filesystem
- Docker/cache disk growth over the run
- Persistent trace-output growth
- Completed, failed, and timed-out instance counts
- Throughput in completed instances per hour

### Per-instance and per-phase metrics

- Phase wall time
- Container CPU-seconds
- Current and peak raw container memory
- Current and peak container working-set memory
- Block read/write bytes
- Peak process count
- Exit status, timeout status, error category, and error message summary

The working-set estimate should be calculated as:

```text
working_set_bytes = memory_usage_bytes - inactive_file_bytes
```

Both raw usage and working set should be retained because Docker and cgroup
versions expose cache accounting differently.

### Trace artifact metrics

Record buggy and patched artifacts separately:

- File count
- Total bytes
- Largest file bytes
- Event count, if it can be emitted without rereading every JSONL file
- Incomplete or missing artifact indicator

Event counts should preferably be emitted by the tracer when it saves its
in-memory event list. A full second read of large JSONL files during the timed
run should be avoided.

## Raw Output Design

Use one resource file per instance to avoid concurrent writes and file locks:

```text
logs/run_evaluation/trace.<agent>.<uid>/<agent>/<instance_id>/resource_usage.json
```

Use a separate run-level file for host samples and aggregate metadata:

```text
logs/run_evaluation/trace.<agent>.<uid>/resource_usage.run.json
```

The per-instance document has this general structure. Exact field types and
nullability are defined by the Phase 1 machine-readable schema:

```json
{
  "schema_version": 1,
  "record_type": "instance",
  "run_id": "trace.<agent>.<uid>",
  "agent": "<agent>",
  "instance_id": "<instance_id>",
  "container": {},
  "outcome": {},
  "measurement": {},
  "container_metrics": {},
  "phases": {
    "buggy_exec": {},
    "buggy_copy_out": {},
    "patched_exec": {},
    "patched_copy_out": {}
  },
  "artifacts": {
    "buggy": {},
    "patched": {}
  }
}
```

Writes should be atomic where practical. A monitor must flush partial results
from a `finally` path before SWE-bench removes its container.

## Implementation Phases

### Phase 1: Metrics schema and semantics

Deliverables:

- [`EXECUTION_TRACE_RESOURCE_SCHEMA.md`](./EXECUTION_TRACE_RESOURCE_SCHEMA.md)
- [`execution/resource_usage.schema.json`](./execution/resource_usage.schema.json)

Tasks:

- Define field names, types, units, optional fields, and schema versioning.
- Define phase boundaries against the installed SWE-bench 4.1.0 execution flow.
- Define CPU-delta, block-I/O, raw-memory, and working-set calculations.
- Decide sampling interval; begin with a proposed interval of one second.
- Define timeout, OOM, Docker error, patch error, and partial-result states.
- Define how cold-cache and warm-cache runs are identified.

Acceptance criteria:

- Example successful, timed-out, and partial JSON records are documented.
- Every reported metric has an explicit unit and source.
- Unsupported Docker/cgroup fields have documented fallbacks.

### Phase 2: Run-level host sampler

Deliverables:

- [`execution/resource_monitor.py`](./execution/resource_monitor.py)
- [`tests/test_resource_monitor.py`](./tests/test_resource_monitor.py)

Tasks:

- Implement a sampler with explicit start, stop, and `finally` cleanup.
- Sample host CPU, memory, swap, load, and relevant filesystem free space.
- Track active tracing containers and aggregate their working sets.
- Record run metadata and raw or summarized samples.
- Keep the sampler independent of individual worker failures.

Acceptance criteria:

- A no-op or short test run produces a valid run-level resource file.
- Interrupting the run still flushes a partial record.
- Measured overhead is small relative to a one-instance trace run.

### Phase 3: Per-container Docker sampler

Deliverables:

- [`execution/docker_resource_monitor.py`](./execution/docker_resource_monitor.py)
- [`tests/test_docker_resource_monitor.py`](./tests/test_docker_resource_monitor.py)

Tasks:

- Collect Docker statistics for each SWE-bench instance container.
- Track cumulative CPU and block-I/O counters.
- Track raw memory, working set, peak memory, and process count.
- Support phase labels and boundary timestamps.
- Handle a container disappearing during cleanup or failure.
- Prefer exact cgroup/Docker memory peaks where supported; retain sampled peaks.

Acceptance criteria:

- A controlled container workload reports credible CPU and memory values.
- Metrics are written when execution succeeds, times out, or raises.
- Sampler threads/connections terminate without leaking resources.

### Phase 4: Integrate with `execution.trace`

Deliverables:

- [`execution/trace.py`](./execution/trace.py)
- [`execution/monkey_patch/trace.py`](./execution/monkey_patch/trace.py)
- [`tests/test_trace_resource_integration.py`](./tests/test_trace_resource_integration.py)

Tasks:

- Start monitoring after the instance container is available.
- Mark buggy execution and copy-out boundaries.
- Wrap the patched execution and copy-out using equivalent measurement paths.
- Finalize metrics before container cleanup.
- Preserve existing test outputs, trace paths, and evaluation behavior.
- Avoid changing tracing semantics or fail-to-pass test selection.

Likely integration files:

- `execution/trace.py`
- `execution/monkey_patch/trace.py`
- A new resource-monitor module under `execution/`

Acceptance criteria:

- Existing tracing results remain unchanged for a fixed test instance.
- Both buggy and patched phases appear in the resource record.
- Concurrent instances write only to their own resource files.

### Phase 5: Trace artifact statistics

Deliverables:

- [`execution/docker_resource_monitor.py`](./execution/docker_resource_monitor.py)
- [`execution/monkey_patch/trace.py`](./execution/monkey_patch/trace.py)
- [`tests/test_docker_resource_monitor.py`](./tests/test_docker_resource_monitor.py)
- [`tests/test_trace_resource_integration.py`](./tests/test_trace_resource_integration.py)

Tasks:

- Measure buggy and patched file counts and sizes after copy-out.
- Record the largest artifact and missing/partial outputs.
- Add a cheap event-count sidecar or save-time counter if justified.
- Separate persistent trace bytes from temporary Docker/cache consumption.

Acceptance criteria:

- Artifact totals agree with filesystem inspection.
- Metrics collection does not reread all large traces during the timed path.

### Phase 6: Automated verification

Deliverables:

- [`tests/test_resource_monitor.py`](./tests/test_resource_monitor.py)
- [`tests/test_docker_resource_monitor.py`](./tests/test_docker_resource_monitor.py)
- [`tests/test_trace_resource_integration.py`](./tests/test_trace_resource_integration.py)

Test cases:

- Successful trace
- Buggy phase timeout
- Patched phase timeout
- Patch application failure
- Docker stats unavailable or missing fields
- Container removed unexpectedly
- Keyboard interrupt/termination where safely testable
- Concurrent writes from multiple workers
- Atomic replacement of an existing partial metrics record

Acceptance criteria:

- Unit tests cover calculations and schema serialization.
- Integration smoke test produces trace files and resource files.
- Existing relevant tests continue to pass.

### Phase 7: One-instance pilot

Run one small supported instance with `--max_workers 1` and validate:

- Phase timing against existing SWE-bench runtime logs
- CPU counters are monotonic and phase deltas are nonnegative
- Sampled and exact peak-memory fields are plausible
- Host and container metrics have aligned timestamps
- Artifact byte totals match copied files
- Monitoring shuts down after success and failure
- Measurement overhead is acceptable

Do not begin the capacity benchmark until pilot anomalies are resolved.

Pilot result (2026-07-18):

- Command: `python -m execution.trace --agent gold --instance_ids django__django-11133 --max_workers 1 --resource-cache-state warm`
- Corrected output: [`logs/run_evaluation/trace.gold.1020`](./logs/run_evaluation/trace.gold.1020)
- The first run exposed a duplicate Python line-trace event around the patched
  multi-line execution call. The preserved diagnostic output is
  `logs/run_evaluation/trace.gold.1020.pilot1-anomalous`.
- `start_patched_exec` is now idempotent while that phase is active, and the
  pinned-hook integration test requires an empty measurement-error list.

| Check | Corrected pilot result |
|---|---|
| SWE-bench outcome | 1 completed, 1 resolved, 0 errors |
| SWE-bench evaluation progress time | 32.25 seconds |
| Run monitor wall time | 120.437 seconds, including dataset metadata startup and final reporting |
| Container monitor wall time | 16.472 seconds |
| Buggy execution | 9.036 seconds measured versus 9.02 seconds logged |
| Patched execution | 6.771 seconds measured versus 6.76 seconds logged |
| Container CPU | 66.231 CPU-seconds; no counter reset errors |
| Container working-set sampled peak | 156,008,448 bytes |
| Container lifetime raw-memory peak | 178,782,208 bytes from Docker `max_usage` |
| Sampling | 36 attempted, 36 successful, 0 failed |
| Trace artifacts | 16,295 buggy bytes + 15,072 patched bytes = 31,367 bytes |
| Trace-output free-space drop at sampled minimum | 20,856,832 bytes; Docker and trace paths share the same filesystem |
| Cleanup | Resource record finalized before cleanup; no pilot container remained |
| Schema and measurement | Both records valid; both `complete`; no missing metrics or errors |
| Runtime comparison | Corrected container lifecycle was 32.22 seconds versus 33.99 seconds in the prior comparable tracked run; no detectable monitoring regression in this single sample |

The host measurements describe a busy shared machine and must not be treated as
minimum hardware requirements. The release will present them as observed
single-worker measurements with explicit limitations.

### Phase 8: Capacity benchmark

#### Single-worker characterization

Run the full supported instance set with one worker. Collect distributions and
maxima for memory, CPU, runtime, and trace size. This establishes the observed
resource profile for the release, not a guaranteed minimum configuration.

#### Optional concurrency characterization (deferred)

Concurrency testing is not required for the current release because
resource-constrained users will be advised to use one worker and the release
will not promise multi-worker throughput. If that promise is added later, build
a stress set containing the largest-memory, largest-output, and longest-running
instances across multiple projects and run it at worker counts:

```text
1, 2, 4, 8
```

Stop increasing concurrency when the host cannot maintain the safety reserve,
swap becomes material, OOM occurs, or timeout rates increase.

#### Optional future validation (deferred)

Run the supported set using the intended recommended worker count. Repeat the
stress set two or three times to estimate variability. Benchmark cold-cache and
warm-cache scenarios separately. Clearing the shared Docker cache requires
separate approval and is not part of the current release evidence.

Benchmark controls:

- Use an otherwise idle host.
- Record swap configuration and do not treat swap-dependent success as enough RAM.
- Fix the software revision, agent set, instance set, timeout, and Docker cache state.
- Record CPU model and storage type because runtime and I/O results are host-specific.
- Retain failure records and exclude nothing silently.

#### Warm-cache single-worker result (2026-07-18 to 2026-07-19)

- Output: [`logs/run_evaluation/trace.gold.1020`](./logs/run_evaluation/trace.gold.1020)
- Run wall time: 45,759.359 seconds (12 hours, 42 minutes, 39 seconds).
- SWE-bench: 291/291 completed, 130 resolved, 161 unresolved, zero harness
  errors. Every resolution status exactly matches the prior `track.gold.1020`
  report, so monitoring introduced no observed outcome regression.
- Resource integrity: one valid run record and 291 valid instance records; all
  measurements complete, 45,663/45,663 host samples successful, zero failed
  container samples, zero OOMs/timeouts/resource errors, and no missing or
  partial artifacts.
- Artifact audit: recorded and independently enumerated totals match exactly at
  126,830,577,708 bytes. Sampled filesystem free-space drop was
  208,799,268,864 bytes and retained drop was 133,669,163,008 bytes. Docker and
  trace output share this filesystem and these values must not be added.
- Throughput: 22.894 completed instances/hour with one worker, including all
  orchestration and cleanup time.
- Scope correction: 266 entries have non-empty gold allowed-function lists;
  25 selected keys have empty lists and emitted warnings. Their measurements
  are valid supplemental observations but they do not define the supported
  workload for release guidance.
- Largest observed instance: `django__django-15563`, with 24,094.125 seconds
  container wall time, 22,309,703,680 bytes sampled working-set peak,
  100,390,178,816 bytes Docker lifetime raw-memory peak, and 98,126,602,039
  persistent artifact bytes. It completed, resolved, did not OOM or time out,
  and accounts for most of the run time and trace storage.
- Timeout semantics: `TRACE_TIMEOUT_SECONDS` is 21,600 seconds and applies
  independently to buggy and patched test execution. It is not a whole
  container-lifetime limit. The 6.7-hour largest observed instance is therefore
  a normal completed run; an instance can approach 12 hours across both test
  phases, plus setup, copy-out, grading, and cleanup time.
- The host remained capacity-safe, but it was shared and began with all 2 GiB
  swap consumed. Host-wide load and memory values are therefore contextual,
  not clean-room requirement measurements.

### Phase 9: Release resource guidance

Deliverable:

- [`PROFILING.md`](./PROFILING.md)

Publish a caution headed "Observed resource profile," not "Minimum hardware
requirements." State that smaller machines were not validated and may run
more slowly, exhaust storage, or terminate because of insufficient memory.

The release guidance must state:

- Tested host, software revision, workload, worker count, and warm-cache state
- Total runtime, observed throughput, and longest instance
- Peak sampled working set and raw Docker memory, explaining reclaimable cache
- Persistent trace footprint, largest artifact, and sampled filesystem drop
- A one-worker default for machines of unknown capacity
- At least 300 GiB suggested free disk for the measured warm-cache full run
- Additional unmeasured space required for cold-cache Docker images
- Separate six-hour buggy/patched timeout semantics and lack of a whole-instance cap
- Largest observed instance
- Timeout and failure rate
- Tested operating system, Docker version, CPU, and storage type
- A clear statement that no smaller minimum-RAM configuration was validated
- No multi-worker capacity or scaling claim

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Sampling misses a short memory peak | Prefer cgroup/Docker peak counters and retain sampled peak as fallback |
| Monitoring changes runtime materially | Keep sampling coarse, measure overhead in the pilot, and avoid rereading traces |
| Docker statistics differ across cgroup versions | Store environment metadata and define optional fields/fallbacks |
| Per-container totals understate host needs | Maintain a separate run-level host monitor |
| Cache/image growth is confused with trace growth | Measure Docker storage and output filesystem separately |
| Worker peaks overlap unpredictably | Default release guidance to one worker; require future empirical concurrency tests before making multi-worker claims |
| Partial failures lose data | Flush from `finally` and use per-instance files with atomic writes |
| Line-based SWE-bench monkey patches are brittle | Test integration against the pinned SWE-bench version and isolate measurement wrappers |

## Decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-18 | Scope measurement to `execution.trace` | Trace generation is the resource-intensive release concern currently under study |
| 2026-07-18 | Optimize the study for hardware capacity guidance | The desired result is useful release-facing resource guidance, not only internal profiling |
| 2026-07-18 | Measure host and container resources separately | Container attribution alone cannot predict safe concurrent host capacity |
| 2026-07-18 | Store per-instance raw resource records | Avoid concurrent append/locking problems and preserve evidence for later aggregation |
| 2026-07-18 | Distinguish cold-cache and warm-cache measurements | Docker image/setup capacity and routine tracing capacity answer different user questions; the current release benchmark was later limited to warm-cache operation |
| 2026-07-18 | Use resource schema version 1 with explicit unit suffixes | Make values machine-checkable and avoid ambiguous display units |
| 2026-07-18 | Sample every second and take one-shot phase-boundary snapshots | Balance monitoring overhead with useful peak and counter attribution |
| 2026-07-18 | Aggregate samples online by default | Avoid producing another large time-series artifact during trace generation |
| 2026-07-18 | Separate workload outcome from measurement completeness | A successful trace and a successful monitor are independent outcomes |
| 2026-07-18 | Read Linux host metrics from `/proc` and `statvfs` | Avoid adding a runtime dependency and preserve the Phase 1 formulas exactly |
| 2026-07-18 | Accept a pluggable container-aggregate provider | Let the host sampler remain independent while Phase 3 supplies Docker working sets |
| 2026-07-18 | Write run records with sibling temporary files and `os.replace` | Preserve a prior valid record and avoid exposing partially written JSON |
| 2026-07-18 | Use Docker one-shot stats when API version is at least 1.41 | Avoid the extra cycle delay of the default non-streaming stats request |
| 2026-07-18 | Serialize background and phase-boundary Docker samples | Prevent concurrent API calls from reordering cumulative counters |
| 2026-07-18 | Require at least two snapshots for counter deltas | A single cumulative snapshot cannot establish CPU or I/O consumed during an interval |
| 2026-07-18 | Discover run containers by exact SWE-bench name suffix | Exclude unrelated containers whose names only contain the run ID |
| 2026-07-18 | Use source-statement identifiers for new SWE-bench hooks | Avoid attaching callbacks to comments, blank lines, or shifting raw line numbers |
| 2026-07-18 | Aggregate active container working sets from the in-memory monitor registry | Avoid duplicating one Docker stats call per active container in the host sampler |
| 2026-07-18 | Keep monitoring best-effort and enabled by default | Resource failures are logged without changing trace execution; users retain an explicit opt-out |
| 2026-07-18 | Leave artifact fields missing until Phase 5 | Keep Phase 4 scoped to execution integration and make incompleteness explicit in schema status |
| 2026-07-18 | Enumerate trace files from filesystem metadata after copy-out | Measure persistent storage without rereading potentially large JSONL contents |
| 2026-07-18 | Leave artifact event counts null in schema v1 | The tracer has no save-time counter sidecar; counting JSONL lines would add avoidable I/O to the measured workload |
| 2026-07-18 | Treat incomplete copies and scan errors as partial artifacts | Preserve any observed files without presenting a lower-bound byte count as complete |
| 2026-07-18 | Make the patched-execution transition idempotent | Python can emit the same line-trace event twice around the multi-line call; repeated callbacks must not truncate the phase |
| 2026-07-18 | Use `django__django-11133` for the warm-cache pilot | It is supported, not excluded, small, previously resolved, and its SWE-bench image was cached locally |
| 2026-07-19 | Define supported benchmark entries as non-empty allowed-function lists | Empty lists trigger the `none` fallback and cannot establish the intended filtered tracing workload |
| 2026-07-19 | Treat the single-worker benchmark as sufficient for this release | The release will warn about observed resource demand and recommend one worker rather than promise multi-worker capacity |
| 2026-07-19 | Publish observations rather than minimum requirements | The powerful-host run measures demand but does not validate success on a smaller constrained machine |
| 2026-07-19 | Defer concurrency and cold-cache tests | They are unnecessary without a multi-worker promise and cold-cache setup would modify a large shared Docker cache |
| 2026-07-19 | Interpret the six-hour timeout per test phase | Buggy and patched execution each receive 21,600 seconds; total container lifetime can exceed six hours normally |
| 2026-07-19 | Publish the result only in `PROFILING.md` | Keep the README unchanged and keep all user-facing resource guidance in one file |
| 2026-07-19 | Use ASD-STE100 rules for the user-facing profile | Use short sentences, simple terms, active voice, and a clear topic structure |

## Progress Log

### 2026-07-19

- Completed Phase 9 and the revised single-worker resource-measurement plan.
- Published [`PROFILING.md`](./PROFILING.md) with the benchmark conditions,
  resource results, operating guidance, timeout behavior, and test limits.
- Rewrote the profile for users with ASD-STE100 rules and kept the README
  unchanged.
- Recomputed the 266-instance supported-workload percentiles and total container
  CPU consumption directly from the instance resource records before publishing.
- Completed and audited the warm-cache single-worker characterization after
  12:42:39: all 291 harness jobs completed with zero harness errors.
- Validated the run record and all 291 instance records against schema v1;
  every measurement is complete and no sample, OOM, timeout, artifact, or
  resource-monitoring error was found.
- Independently enumerated every regular trace file and exactly matched the
  126,830,577,708-byte run total with no per-instance mismatch.
- Compared all resolution outcomes with `track.gold.1020` and found zero
  differences, confirming that the monitored run preserved the prior behavior.
- Identified 25 entries with empty allowed-function lists; retained their data
  but narrowed the supported analysis set to the 266 non-empty entries.
- Identified `django__django-15563` as the dominant time, memory, and storage
  outlier and retained it as the release worst-case observation.
- Confirmed that no benchmark container remains and completed Phase 8 under the
  revised single-worker scope. Concurrency and cold-cache testing are deferred.
- Documented that the configured six-hour timeout applies independently to
  buggy and patched test execution; the observed 6.7-hour container lifetime
  is expected and did not time out.

### 2026-07-18

- Started Phase 8 with the warm-cache, single-worker characterization of all
  291 selected gold keys; none overlap the configured exclusion list. The
  later audit refined the supported subset to 266 non-empty entries.
- Preflight recorded 1.1 TiB host-available memory and 5.4 TiB free disk. The
  host is shared, has one unrelated long-running container, and began with its
  2 GiB swap already consumed; retain these as host-baseline limitations and
  do not interpret host-wide usage deltas as clean-room measurements.
- Launched the 291-instance run at 12:54 Asia/Singapore with all instance images
  already cached. The first checkpoint reached 4/291 in 4:52 with zero harness
  errors and a rolling estimate of approximately 5 hours 49 minutes at that
  checkpoint.
- Started and completed Phase 7 with a real warm-cache, single-worker gold
  trace of `django__django-11133`.
- The first pilot completed but revealed a duplicate patched-execution hook;
  preserved that run, made the transition idempotent, and added a regression
  assertion requiring no integration-record errors.
- Reran from a clean output path: 1/1 completed and resolved in 32.25 seconds,
  with complete run and instance measurements and no errors.
- Validated both resource records against the JSON schema, matched execution
  phase timings to SWE-bench logs, and confirmed nonnegative/reset-free counters.
- Matched recorded artifact sizes exactly to the two copied trace files and
  confirmed the corrected run aggregated 31,367 persistent bytes.
- Confirmed plausible sampled/exact container memory peaks, aligned run,
  instance, sample, and phase timestamps, and successful container removal.
- Compared against the prior comparable tracked run and found no detectable
  runtime regression in this single sample; this is a smoke check, not a
  statistically meaningful overhead benchmark.
- Verified the pinned-hook regression test (`5 passed`) and full suite
  (`46 passed`), plus schema validation and whitespace checks.
- Started and completed Phase 6: automated failure-path verification.
- Covered successful tracing, buggy and patched timeouts, patch-application
  failure, missing Docker fields, unavailable stats, and container disappearance.
- Verified host `KeyboardInterrupt` and instance `SystemExit` persistence,
  including interrupted active phases and stopped sampler threads.
- Exercised eight simultaneous instance monitors and confirmed isolated,
  atomically written records without leftover temporary files.
- Verified replacement of an existing incomplete record and preservation of the
  previous record when atomic replacement itself fails.
- Confirmed the pinned-hook integration smoke writes trace artifacts and a
  schema-valid resource file without requiring a real SWE-bench pilot.
- No production-code changes were required after adding the Phase 6 cases.
- Verified the focused resource suite (`26 passed`) and full suite (`46 passed`),
  plus Python compilation and whitespace checks.
- Started and completed Phase 5: trace artifact statistics.
- Added recursive metadata-only enumeration of regular trace files, excluding
  symlinks and recording file count, total bytes, and largest-file bytes.
- Collected buggy and patched artifact statistics immediately after successful
  copy-out, with a cleanup-time fallback that preserves partially copied files.
- Propagated exact persistent trace-byte totals into the run summary; a partial
  filesystem scan makes the aggregate unavailable rather than undercounting.
- Kept `event_count` null because the tracer does not emit a save-time counter
  sidecar and reading JSONL contents would distort the workload being measured.
- Added complete, missing, and partial artifact tests and extended the pinned
  hook integration test to validate artifact values and the run-level total.
- Verified the focused Phase 5 suite (`13 passed`) and full suite (`38 passed`),
  plus Python compilation and whitespace checks.
- Started Phase 4: integrate resource monitoring with `execution.trace`.
- Completed Phase 4 by wrapping the top-level evaluation in the host monitor
  and registering per-instance monitoring before tracer archive installation.
- Added phase transitions for tracer archive copy, buggy prepare/execute/copy,
  patch application, patched prepare/execute/copy, and grading.
- Finalized instance records immediately before SWE-bench container cleanup and
  aggregated instance outcomes into the run record.
- Added `--resource-sample-interval`, `--resource-cache-state`, and
  `--disable-resource-monitoring`; monitoring defaults to enabled.
- Used the shared in-memory instance registry to supply active-container count
  and aggregate working set to the host sampler without extra Docker polling.
- Added two integration tests that execute the pinned SWE-bench `run_instance`
  hook flow with a fake container and exercise the monitored CLI orchestration.
- Verified that buggy and patched trace copy-out each still run once, all nine
  observable phases complete, the schema-valid resource file exists before
  cleanup, and the monitor registry is empty afterward.
- Verified the combined resource suite (`15 passed`) and full suite
  (`35 passed`), plus Python compilation and whitespace checks.
- Verified the `execution.trace --help` surface with the new resource options.
- Deferred a real SWE-bench trace run to the explicit Phase 7 pilot.
- Started Phase 3: per-container Docker sampler.
- Completed Phase 3 with Docker stats parsing, phase-aware online aggregation,
  exact/sampled memory peaks, CPU and block-I/O deltas, PID peaks, configured
  limits, OOM evidence, atomic instance records, and run-level aggregation.
- Serialized background sampling and one-shot boundary snapshots to preserve
  cumulative-counter ordering.
- Added eight focused Docker tests, bringing the combined host/container
  monitor suite to 13 passing tests.
- Verified successful, timed-out, disappearing-container, cgroup v1/v2,
  aggregate-provider, schema-validation, and thread-shutdown paths.
- Verified the full repository suite (`33 passed`).
- Ran a real Redis-container smoke workload: 32 successful samples, zero failed
  samples, schema-valid complete output, and plausible CPU, memory, block-I/O,
  PID, lifetime-peak, and OOM fields.
- Removed the temporary smoke container and verified that it no longer exists.
- Measured 50 Docker one-shot collections at approximately 4.17 ms per sample
  on this daemon, roughly 0.42% of one CPU per monitored container at the
  one-second interval, excluding daemon-side cost.
- Started Phase 2: run-level host sampler.
- Completed Phase 2 with a threaded Linux host sampler, online aggregation,
  environment metadata collection, interruption-safe context management, and
  atomic schema-v1 run-summary output.
- Added a pluggable provider for active trace-container count and aggregate
  working set; Docker-specific collection remains Phase 3.
- Added five focused tests covering parsers/formulas, peak aggregation,
  schema-valid atomic output, interruption flushing, and unavailable sources.
- Verified the focused suite (`5 passed`) and full suite (`25 passed`).
- Ran a real-host smoke monitor that produced a schema-valid complete record
  with four successful samples and no failed samples.
- Measured 200 real host collections at approximately 0.54 ms per sample on
  this host, about 0.05% of one CPU at the one-second default interval. This
  does not include the future Phase 3 Docker polling overhead.
- Started Phase 1: metrics schema and measurement semantics.
- Completed Phase 1 and added the normative schema specification and
  machine-readable JSON Schema.
- Defined phase boundaries, units, sources, formulas, workload outcomes,
  measurement-completeness states, cache semantics, and cgroup v1/v2 fallbacks.
- Validated the JSON Schema structure with Draft 2020-12 and validated three
  complete examples (successful instance, timed-out instance, and run summary)
  against it.
- Confirmed that `execution.trace`, rather than `build_step1`, generates the
  buggy and patched execution traces.
- Established capacity planning as the measurement goal.
- Documented the proposed metrics, instrumentation layers, staged implementation,
  benchmark matrix, acceptance criteria, risks, and release outputs.
- Phase 2 introduced `execution/resource_monitor.py`; it is not yet wired into
  `execution.trace`.
