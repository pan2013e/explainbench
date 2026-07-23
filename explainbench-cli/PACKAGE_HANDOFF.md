# ExplainBench Package Implementation Handoff

## Document status

This document is the current information source for the ExplainBench Python package implementation.
Use the source code and tests as the final authority when this document and the implementation differ.

Status date: 2026-07-23.

This document covers the package implementation only.
It does not explain the research purpose of ExplainBench.

## Status terms

This document uses the following terms:

- **Implemented** means that code exists and the fast automated tests cover it.
- **Partly validated** means that code exists, but the intended Docker, model, or clean-install workflow has not completed.
- **Package-ready** means that the feature works from an installed wheel outside the repository.
- **Not implemented** means that the public workflow does not exist.

These terms keep repository implementation status separate from release status.

## Handoff summary

| Area | Status | Current evidence |
|---|---|---|
| Submission schema and checker | Implemented and package-ready | The checker works from the built wheel with its runtime dependencies available. |
| Evaluation engine | Implemented | Fast tests cover lite, full, and selected-task evaluation with mocked inference. |
| Shared intent resources | Implemented and package-ready | The wheel contains both context files, both ground-truth files, and all 297 supported instance IDs. |
| Effect artifact loading | Implemented | Fast tests cover local and end-to-end effect artifact loading and evaluation. |
| Evaluation checkpoints | Implemented | Fast tests cover compatible resume and checkpoint validation. |
| Local-effect question-builder CLI | Implemented in the repository | The CLI exposes all ten stages, complete runs, status, configuration, checkpoints, and publication. |
| Local-effect scientific stage wrappers | Implemented in the repository | All ten wrappers call and validate their canonical commands. |
| Local-effect real-data validation | Partly validated | Retained evidence confirms `S01` and `S02`; `S03` through `S07` have not run successfully yet. |
| Local-effect wheel execution | Partly validated | The extracted wheel contains all canonical modules, and their installed command help checks pass. |
| Model-backed local-effect workflow | Partly validated | The wrapper exists, but paid inference and complete real-data execution have not been validated. |
| End-to-end effect question builder | Not implemented | End-to-end effect artifacts must be prepared outside the package. |
| Package release verification | Partly validated | Four automated clean-wheel tests pass, but CI and real Docker validation are incomplete. |

The extracted fast test result on 2026-07-23 was:

```text
139 passed, 7 skipped
```

The seven skipped tests are the opt-in real local-effect tests.
The source baseline was 132 passed and 7 skipped.
The seven added passing tests are two extraction checksum tests, one tracer-payload regression test, and four clean-wheel integration tests.
The standalone tracer checks also reported 17 inspector before-mode passes, 17 inspector after-mode passes, and 12 serializer passes with 3 optional-library skips.

## Package boundary

The project uses a `src` package layout.
The public package is under `src/explainbench`.
The project version is `0.1.0`.
The minimum Python version is 3.12.
The console entry point is:

```toml
[project.scripts]
explainbench = "explainbench.cli:main"
```

The original research-repository wheel contains:

- The `explainbench` package.
- The evaluation implementation.
- The local question-builder orchestration and wrappers.
- The benchmark instance ID list.
- The shared local-intent and end-to-end-intent artifacts.

The built wheel does not contain:

- The canonical modules under `dataset`.
- The canonical modules under `execution`.
- The repository examples.
- The end-to-end question-builder implementation.

The extracted package workspace at `explainbench-cli/` now includes the missing canonical modules.

## Current architecture

The package has three public command groups:

```text
explainbench
├── checker
├── evaluate
└── question-builder
    └── local
```

The checker and evaluator run from code under `src/explainbench`.

The local question builder has two layers:

```text
public CLI and orchestration under src/explainbench
  -> canonical Python module command
  -> scientific implementation under dataset or execution
```

The package layer owns:

- Submission adaptation.
- Typed configuration.
- Stage dependency resolution.
- Workspace locking.
- Per-instance checkpoints.
- Retry and resume behavior.
- Subprocess command records.
- Output validation.
- Final artifact publication.

The canonical modules own:

- Patched-function detection.
- Test-call tracking.
- Detailed tracing.
- Divergence analysis.
- Candidate expression generation.
- Candidate expression execution.
- Candidate expression validation.
- Answer-choice construction.
- Final context and ground-truth construction.

The current wrappers call canonical modules in subprocesses.
This behavior is intentional because it provides process isolation, command timeouts, process-group cleanup, and durable logs.
The old statement that the CLI must not use subprocesses is no longer the active design.

Scientific logic must have one implementation.
Do not copy the scientific logic into the package wrappers.

## Submission contract

All public commands use one JSON submission document:

```json
{
  "submission_id": "my-agent",
  "instances": [
    {
      "instance_id": "astropy__astropy-12907",
      "model_patch": "diff --git a/example.py b/example.py\n...",
      "explanation": "The patch changes the returned value."
    }
  ]
}
```

The common validation rules are:

- The input must be valid UTF-8 JSON.
- Duplicate JSON fields are invalid.
- Unknown fields are invalid.
- `submission_id` must be a nonempty string.
- `instances` must be a nonempty list.
- Every `instance_id` must be unique and supported by ExplainBench.
- Every explanation must be a nonempty string.
- A supplied patch must have the basic structure of a Git unified diff.

The base and lite profiles do not require a patch.
Effect evaluation, full evaluation, and local question building require a nonempty patch for every selected instance.

Effect artifact filenames also require a safe submission ID.
A safe ID starts with a letter or number and contains only letters, numbers, `.`, `_`, and `-`.
The base checker does not currently apply this filename rule.
The effect artifact loader and final local-effect export apply it later.

## Submission checker

Run:

```bash
explainbench checker submission.json
```

The checker reports the submission ID and the counts of instances, explanations, and patches.
It does not run patches.
It does not inspect Docker or system dependencies.
It uses the base validation profile, so it does not require every instance to have a patch.

## Evaluation implementation

### Supported tasks

The evaluator supports four task names:

| Task | Artifact owner |
|---|---|
| `e2e.intent` | ExplainBench package |
| `local.intent` | ExplainBench package |
| `e2e.effect` | Submission |
| `local.effect` | Submission |

Intent artifacts are shared package resources.
Effect artifacts depend on the submitted patch and are loaded from a user-selected artifact directory.

### Mode presets

Lite mode selects:

```text
e2e.intent
local.intent
```

Full mode selects:

```text
e2e.intent
e2e.effect
local.intent
local.effect
```

Users can also repeat `--task` to select tasks directly.
`--mode` and `--task` are mutually exclusive.

### Main commands

Run lite evaluation:

```bash
explainbench evaluate submission.json \
  --mode lite \
  --output results.json
```

Run full evaluation:

```bash
explainbench evaluate submission.json \
  --mode full \
  --artifacts-dir question-artifacts \
  --output results.json
```

Run selected tasks:

```bash
explainbench evaluate submission.json \
  --task local.intent \
  --task local.effect \
  --artifacts-dir question-artifacts \
  --output results.json
```

### Evaluation configuration

The evaluator accepts a strict TOML configuration with `schema_version = 1`.
Command-line values override configuration values.
Configuration values override package defaults.
Relative paths in the configuration are resolved from the configuration file directory.
Unknown fields and unsupported schema versions are invalid.

The configuration controls:

- Task selection.
- Evaluator model.
- Number of generations.
- Instance and generation concurrency.
- Temperature and top-p.
- Token and retry limits.
- Result path.
- Effect artifact path.
- Optional dotenv path.

### Artifact contract

Shared intent files are package resources:

```text
explainbench/data/context/e2e_intent.json
explainbench/data/context/local_intent.json
explainbench/data/ground_truths/e2e_intent.json
explainbench/data/ground_truths/local_intent.json
```

Submission-owned effect files use this layout:

```text
question-artifacts/
├── context/
│   ├── e2e_effect__SUBMISSION_ID.json
│   └── local_effect__SUBMISSION_ID.json
└── ground_truths/
    ├── e2e_effect__SUBMISSION_ID.json
    └── local_effect__SUBMISSION_ID.json
```

The evaluator validates each selected context and ground-truth pair before inference.
The evaluator reports submitted, evaluated, skipped, and failed instance counts for each task.
A selected task with no evaluable instances fails before inference.

### Results and resume

Evaluation writes one versioned JSON result document.
The result includes:

- Submission and task selection.
- Non-secret evaluator settings.
- Token usage.
- Per-task statistics.
- Per-instance predictions and scores.
- Skipped instance IDs.
- Failure details.

The CLI writes a sidecar checkpoint next to the requested result.
The checkpoint suffix is `.checkpoint.jsonl`.
Use `--resume` to reuse compatible completed task-instance results.

The checkpoint fingerprint includes the submission, selected tasks, artifacts, model, generation count, sampling settings, and token limit.
Concurrency and retry-count changes do not invalidate completed results.
A successful run removes the checkpoint.
A failed or interrupted run keeps the checkpoint.

### Evaluation status

The source implementation and fast tests cover:

- Lite mode.
- Full mode.
- Direct task selection.
- Shared intent resource loading.
- Effect artifact loading.
- Typed artifact validation.
- Inference integration through a model adapter.
- Scoring.
- Result serialization.
- Progress reporting.
- Resume checkpoints.
- Legacy evaluation compatibility wrappers.

The current repository does not contain an automated test that builds a wheel, installs it in a clean environment, and runs the evaluator.
The wheel audit confirmed that all four shared intent files and all 297 instance IDs are present.

## Local-effect question builder

### Public commands

List the stages:

```bash
explainbench question-builder local stages
```

Run the complete pipeline:

```bash
explainbench question-builder local run submission.json \
  --workspace .explainbench/builds/my-agent \
  --output question-artifacts \
  --resume
```

Run one stage:

```bash
explainbench question-builder local stage find-first-divergence \
  submission.json \
  --workspace .explainbench/builds/my-agent \
  --resume
```

Inspect a workspace:

```bash
explainbench question-builder local status \
  --workspace .explainbench/builds/my-agent
```

The `run` command requires an output directory.
The `export-question-artifacts` stage also requires an output directory.
Other individual stages do not require an output directory.

### Stage sequence

The local pipeline has ten registered stages:

| Order | Public stage | Canonical module or command |
|---:|---|---|
| 1 | `identify-patched-functions` | `dataset.extract_ground_truths.effect.trace_step1_generate_qualname_whitelist` |
| 2 | `track-test-calls` | `execution.track` |
| 3 | `select-trace-functions` | `dataset.extract_ground_truths.effect.trace_step2_generate_call_stack_whitelist` |
| 4 | `trace-program-state` | `execution.trace` |
| 5 | `find-first-divergence` | `dataset.extract_ground_truths.effect.build_step1` |
| 6 | `generate-candidate-expressions` | `dataset.extract_ground_truths.effect.build_step2` |
| 7 | `execute-candidate-expressions` | `dataset.extract_ground_truths.effect.build_step3 --execute` |
| 8 | `validate-candidate-expressions` | `dataset.extract_ground_truths.effect.build_step3 --validate` |
| 9 | `build-answer-choices` | `dataset.extract_ground_truths.effect.build_step4` |
| 10 | `export-question-artifacts` | `dataset.extract_ground_truths.effect.build_step5` |

All ten stage definitions use real package runners.
No registered stage uses the old unconnected placeholder.

### Configuration

The local builder accepts a strict TOML configuration with `schema_version = 1`.
It also exposes command-line overrides.

The configuration covers:

- Workspace and artifact output paths.
- Repository cache and benchmark source.
- Per-stage timeouts.
- Worker limits.
- Retry limits.
- Candidate model and reasoning effort.
- Candidate counts.
- Optional candidate inference.
- Candidate model credentials.
- Expression inspection settings.
- Answer-choice settings.
- Export limits.

Run `explainbench question-builder local run --help` for the complete option list.

### Workspace and checkpoints

The workspace contains private and resumable build state.
The artifact output contains only the evaluator input.

The checkpoint unit is one stage and one instance.
Each unit can be pending, running, completed, skipped, failed, or stale.
Each attempt has its own directory, command record, standard output log, and standard error log.
Large trace and inspection outputs have size and SHA-256 records.

The workspace uses:

- A versioned manifest.
- A normalized submission snapshot.
- A canonical predictions file.
- A single-writer lock.
- Semantic and execution fingerprints.
- Per-invocation retry cycles.
- Cumulative attempt history.

`--resume` reuses compatible completed work.
A semantic input change invalidates the affected stage and its downstream stages.
Operational changes, such as a worker-count change, apply to new work without invalidating completed semantic results.
The implementation validates saved external artifacts before it reuses a checkpoint.

### Publication

The final stage creates:

```text
context/local_effect__SUBMISSION_ID.json
ground_truths/local_effect__SUBMISSION_ID.json
artifact-manifest.json
```

The publisher merges successful per-instance records.
It validates the merged artifact pair with the evaluator artifact loader.
It writes an immutable generation under the workspace.
It then switches the public output path to that generation with a symbolic link.
It refuses to overwrite a nonempty unmanaged output directory.

### Repository implementation status

The repository implementation includes:

- The stage registry and dependency graph.
- Typed local-builder configuration.
- All ten canonical command wrappers.
- Output validation for all ten stages.
- Durable subprocess records and logs.
- Per-instance retries and resume.
- Corrupt-artifact detection.
- Semantic skip propagation.
- Final artifact validation and publication.
- Fast tests that replace Docker and model calls with controlled test doubles.

### Real-data validation status

The opt-in test module defines scenarios `S01` through `S07`.
The retained evidence currently contains:

- `S01`: submission validation completed.
- `S02`: patched-function identification completed.
- `S02` resume: the completed checkpoint was reused.

The retained evidence does not contain completed runs for `S03` through `S07`.
The current default test run skips all seven real-data tests.

The next unpaid real-data sequence is:

1. Run `S03` to track real test calls with Docker.
2. Run `S04` to select trace functions.
3. Run `S05` to record detailed traces.
4. Run `S06` to find a real divergence.
5. Run `S07` with candidate inference disabled.
6. Review the saved divergence and candidate metadata.

The fixed test instance is `sympy__sympy-15349`.
The default real-test workspace is `.explainbench/real-tests/sympy-15349`.

### Model persistence gap

The candidate-generation stage stores prompt length and parsed candidate data.
It does not store the complete raw prompt.
It does not store each raw model response before parsing.

Add durable raw prompt and raw response records before the first paid end-to-end validation.
Store these records in the stage attempt directory.
Record checksums for these files.
Do not move or copy the scientific prompt construction into the package wrapper.

### Wheel blocker

The original research-repository wheel includes the local builder wrappers but excludes their canonical modules.
A run from that original wheel fails with:

```text
ModuleNotFoundError: No module named 'dataset'
```

This historical failure occurs because the runner invokes:

```text
python -m dataset.extract_ground_truths.effect.trace_step1_generate_qualname_whitelist
```

The selected extraction design keeps the current import names.
It copies the required canonical modules under `src/core` in a new package-focused repository.
The wheel maps the children of `src/core` to their current top-level package names.
This design avoids changes to the current scientific implementation during extraction.

The extraction now contains `dataset`, `evaluation`, `execution`, `tracer`, and `tracer_plugin`.
The built extraction wheel installs these modules as their current top-level import names.
The `core` repository container is not an installed import package.
The extraction also builds the Docker tracer payload from the installed tracer packages.

The complete structure, migration tracker, and acceptance criteria are in [EXPLAINBENCH_CLI_EXTRACTION_PLAN.md](EXPLAINBENCH_CLI_EXTRACTION_PLAN.md).

## End-to-end effect question builder

The package does not implement:

```bash
explainbench question-builder end2end ...
```

The evaluator can consume end-to-end effect artifacts.
The example full artifact directory contains a staged end-to-end effect pair.
Another process must create or stage this pair.

Do not describe full evaluation support as full question-builder support.
These are separate package capabilities.

## Known package gaps

### Release blockers

- The clean-wheel tests are not in CI.
- The complete local-effect workflow has not passed real Docker and model validation.

### Validation gaps

- Real scenarios `S03` through `S07` have not completed.
- Paid candidate generation has not completed in the real workflow.
- Expression execution and validation have not completed in the real workflow.
- Final local-effect publication has not completed in the real workflow.
- Evaluation of a newly generated local-effect artifact has not completed.
- Interruption, retry exhaustion, corruption, and semantic invalidation have not been validated with real external processes.

### Auditability gaps

- Candidate generation does not persist the full raw prompt.
- Candidate generation does not persist each raw model response before parsing.

### Feature gaps

- The end-to-end effect question builder is not implemented.
- The evaluator does not build missing effect artifacts automatically.
- Docker and system dependency diagnostics are not implemented.
- Automatic cleanup of large traces and Docker artifacts is not implemented.

### Distribution metadata gaps

- The package metadata does not contain the usual release fields such as license, authors, and project URLs.
- The repository examples are not present in the wheel.
- All dependencies are mandatory and exactly pinned.
- Optional dependency groups for evaluation-only and builder workflows do not exist.

These metadata items do not block repository development.
They should be complete before a public package release.

## Recommended work order

The package extraction and release work is tracked in [EXPLAINBENCH_CLI_EXTRACTION_PLAN.md](EXPLAINBENCH_CLI_EXTRACTION_PLAN.md).

### Priority 1: Complete unpaid real validation

1. Run and review `S03` through `S07`.
2. Fix any Docker, path, timeout, or artifact problems.
3. Confirm that resume does not repeat completed expensive work.

### Priority 2: Improve paid-work durability

1. Store the raw candidate prompt before inference.
2. Store every raw model response before parsing.
3. Add checksums and checkpoint references.
4. Confirm that resume can reuse paid outputs.

### Priority 3: Complete one real local-effect workflow

1. Run model-backed candidate generation.
2. Execute candidate expressions.
3. Validate candidate expressions.
4. Build answer choices.
5. Export local-effect artifacts.
6. Run `explainbench evaluate --task local.effect` with the generated artifacts.
7. Repeat the complete run with `--resume`.

### Priority 4: Complete release verification

1. Add the fast and clean-wheel tests to CI.
2. Add a separate opt-in Docker integration job.
3. Complete the release metadata and installation documentation.

### Priority 5: Decide the end-to-end builder scope

Implement the end-to-end builder only after the local builder is package-ready.
Reuse the common orchestration components when they match the end-to-end pipeline.
Do not force both pipelines to use the same scientific stages.

## Package-ready acceptance criteria

The package is ready for handoff as an installable implementation when all of these statements are true:

- A clean wheel contains every module and resource required by the selected workflow.
- `explainbench --help` works outside the repository.
- `explainbench checker` works outside the repository.
- Lite evaluation loads its shared artifacts outside the repository.
- Full evaluation loads supplied local and end-to-end effect artifacts outside the repository.
- The local builder completes one real instance from an installed wheel.
- The local builder resumes without repeating compatible completed work.
- The generated local-effect artifact passes the evaluator loader.
- The evaluator scores the generated local-effect artifact.
- The fast tests pass.
- The opt-in real integration result is recorded.
- Package installation, Docker, disk, network, credentials, runtime, and cleanup requirements are documented.

## Verification commands

Run the fast suite:

```bash
uv run pytest -q
```

List the local stages:

```bash
uv run explainbench question-builder local stages
```

Run the current real scenarios only when Docker is available:

```bash
EXPLAINBENCH_RUN_REAL_LOCAL_EFFECT=1 \
uv run pytest -s tests/real_local_effect/test_s01_s07_real_pipeline.py
```

Build a wheel:

```bash
uv build --wheel
```

Inspect the wheel before a release:

```bash
unzip -l dist/explainbench-*.whl
```

Do not mark the local builder as package-ready until a builder stage works from that installed wheel outside the repository.
