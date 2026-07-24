# Real local-effect tests

This directory contains opt-in tests that use real ExplainBench submissions and canonical SWE-bench execution.
The normal test suite collects these tests but skips them unless they are explicitly enabled.

The first module covers scenarios `S01` through `S07` from the real-data validation section in [PACKAGE_HANDOFF.md](../../PACKAGE_HANDOFF.md).
It uses `examples/submission-full.json` and the real `sympy__sympy-15349` instance.

## Requirements

- Install ExplainBench so that the `explainbench` command is available.
- Make the Docker daemon available to the current user.
- Provide enough disk space for SWE-bench images, repositories, and trace logs.
- No model API credentials are required for `S01` through `S07`.

## Run all first-sequence scenarios

```bash
EXPLAINBENCH_RUN_REAL_LOCAL_EFFECT=1 \
pytest -s tests/real_local_effect/test_s01_s07_real_pipeline.py
```

## Run one scenario

```bash
EXPLAINBENCH_RUN_REAL_LOCAL_EFFECT=1 \
pytest -s \
  tests/real_local_effect/test_s01_s07_real_pipeline.py::test_s03_tracks_real_test_calls_and_reuses_artifacts
```

Every later scenario automatically runs or reuses its required earlier stages.
This allows one test to run independently without relying on pytest test ordering.

## Workspace and evidence

The default workspace is:

```text
.explainbench/real-tests/sympy-15349
```

The command evidence file is written next to the workspace:

```text
.explainbench/real-tests/sympy-15349-evidence.json
```

The evidence file records every command, start time, duration, exit status, standard output, and standard error.
The workspace retains canonical command records, attempt history, logs, results, and checksummed external artifacts.

Override the workspace when a separate run is required:

```bash
EXPLAINBENCH_RUN_REAL_LOCAL_EFFECT=1 \
EXPLAINBENCH_REAL_WORKSPACE=/tmp/explainbench-sympy-15349 \
pytest -s tests/real_local_effect/test_s01_s07_real_pipeline.py
```

Use `EXPLAINBENCH_REAL_EXECUTABLE` to select a specific installed CLI.
Without this setting, the tests prefer the `explainbench` executable beside the Python interpreter that runs pytest.
They use the executable from `PATH` only when that environment does not provide one.
Use `EXPLAINBENCH_REAL_COMMAND_TIMEOUT_SECONDS` to change the outer per-command timeout.

## Paid inference boundary

Scenario `S07` passes `--no-candidate-inference` and must not call a model API.
The seven opt-in tests remain unpaid so that an explicit test run cannot create an unexpected model charge.

Phase 11 separately completed one model-backed workflow for `sympy__sympy-15349`.
That validation generated candidates, executed and validated expressions, built answer choices, published local-effect artifacts, and evaluated the generated artifact.
The repeated complete builder command reused all ten compatible stages and did not make another candidate request.

The paid Phase 11 run is retained as workspace evidence.
It is not an automated test because model-backed execution requires explicit approval for cost and data transfer.
