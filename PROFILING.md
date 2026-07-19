# Resource Profile for Local Effect Tracing

## Caution

**CAUTION: LOCAL EFFECT TRACING CAN USE LARGE AMOUNTS OF MEMORY, DISK SPACE,
CPU TIME, AND RUN TIME.**

Insufficient memory or disk space can stop a trace run.

This profile contains measurements from one test. It does not give minimum
hardware requirements. We did not test a smaller computer.

## Recommendation

Use `--max_workers 1` when you do not know the capacity of the computer.

Use at least 300 GiB of free disk space for the same full warm-cache test.
This value applies when Docker and the traces share one filesystem.

If Docker and the traces use different filesystems, check each filesystem.
Do not divide the 300 GiB value between the filesystems.

A cold-cache run needs more disk space for Docker images. We did not measure
this additional disk space.

Do not use the memory values in this profile as minimum RAM values. Keep free
memory for Docker, the operating system, and other processes.

Use `--instance_ids` to run smaller groups if the full test is too large.

## Test Configuration

We did the test from July 18 to July 19, 2026. The local time zone was
Asia/Singapore.

| Item | Test value |
|---|---|
| Workload | 291 gold instances |
| Primary workload | 266 instances with a nonempty allowed-function list |
| Additional workload | 25 instances with an empty allowed-function list |
| Worker count | 1 |
| Docker cache | Warm |
| Sample interval | 1 second |
| Operating system | Ubuntu 20.04.6 LTS |
| Processor | AMD EPYC 9554 |
| Logical processors | 256 |
| RAM | 1.48 TiB |
| Swap | 2 GiB |
| Docker | Version 28.0.1, API 1.48, `overlay2` |
| Python | Version 3.12.3 |
| SWE-bench | Version 4.1.0 |

All Docker images were in the cache before the test. Docker and the trace
output used the same filesystem.

Other work also used the test computer. The 2 GiB swap area was full before
the test started. Thus, host values include other work.

## Full Test Results

| Resource | Measured value |
|---|---:|
| Run time | 12 hours, 42 minutes, 39 seconds |
| Completed instances | 291 of 291 |
| Processing rate | 22.894 instances per hour |
| Container CPU time | 14.46 CPU-hours |
| Stored trace files | 118.1 GiB |
| Maximum decrease in free disk space | 194.5 GiB |
| Decrease in free disk space after test | 124.5 GiB |
| Maximum working set (sampled) | 20.8 GiB |
| Timeouts | 0 |
| Out-of-memory stops | 0 |
| Test harness errors | 0 |
| Host samples | 45,663 successful and 0 failed |

The stored trace-file value is exact. The test measured 126,830,577,708 bytes
of trace files.

The filesystem values are sampled values from a shared filesystem. Other work
on the computer can change these values.

## Results for One Instance

The next table uses the 266 instances in the primary workload.

| Resource | Median | 95th percentile | Maximum |
|---|---:|---:|---:|
| Container run time | 17.8 seconds | 3 minutes, 17 seconds | 6 hours, 41 minutes, 34 seconds |
| Sampled working set | 151.8 MiB | 441.6 MiB | 20.8 GiB |
| Docker raw memory | 186.9 MiB | 771.6 MiB | 93.5 GiB |
| Stored trace files | 0.59 MiB | 457.8 MiB | 91.4 GiB |
| Container CPU time | 58.4 seconds | 3 minutes, 56 seconds | 6 hours, 43 minutes, 38 seconds |

The maximum values came from `django__django-15563`. This instance made 91.4
GiB of trace files. It caused most of the disk use and run time.

The sampled working set estimates active memory. Docker raw memory also
includes file cache. The operating system can reclaim some file cache.

Neither memory value is a minimum RAM requirement.

## Timeout

`execution.trace` gives six hours to the buggy test phase. It gives another six
hours to the patched test phase.

The six-hour value does not apply to the full container run. Setup, trace copy,
grading, and cleanup are outside these two limits.

Thus, one container can run for almost 12 hours plus additional time. The 6.7-hour
maximum in this test was normal. Both test phases completed before their limits.

## Resource Files

Resource measurement is on by default. The run record has this path:

```text
logs/run_evaluation/trace.{AGENT_ID}.{UID}/resource_usage.run.json
```

Each instance directory contains a `resource_usage.json` file. These files give
memory, CPU, disk, phase time, timeout, and error data.

Use `--resource-sample-interval` to change the one-second sample interval. Use
`--disable-resource-monitoring` to turn off resource measurement.

## Limits of This Profile

This profile applies to one warm-cache test with one worker. It does not include
a cold-cache test.

This profile does not show multi-worker capacity. It does not show performance
on a smaller computer.
