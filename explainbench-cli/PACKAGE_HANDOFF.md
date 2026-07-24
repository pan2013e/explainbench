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
| Local-effect real-data validation | Implemented and validated | Real scenarios `S01` through `S07` pass from the extracted package with Docker and inference disabled. |
| Local-effect wheel execution | Package-ready for unpaid stages | The extracted wheel contains all canonical modules, and `S01` through `S07` pass from its installed CLI. |
| Paid inference persistence | Implemented | Tests confirm atomic prompt and response storage, checksums, source links, interruption recovery, and no repeated compatible request. |
| Model-backed local-effect workflow | Implemented and validated | One complete real workflow generated, loaded, and evaluated an artifact for `sympy__sympy-15349`. |
| End-to-end effect question builder | Not implemented | End-to-end effect artifacts must be prepared outside the package. |
| Package release verification | Partly validated | Clean-wheel, real Docker, paid candidate generation, and real evaluation checks pass, but release CI is incomplete. |

The extracted test result on 2026-07-24 was:

```text
146 passed, 7 skipped
```

The seven skipped tests are the opt-in real local-effect tests.
The source baseline was 132 passed and 7 skipped.
The added tests cover extraction checksums, the tracer payload, clean-wheel execution, paid-work persistence, and safe child-module resolution.
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
The retained evidence contains successful runs for all seven scenarios:

- `S01`: submission validation completed.
- `S02`: patched-function identification completed.
- `S03`: real test-call tracking completed.
- `S04`: trace-function selection completed.
- `S05`: detailed program tracing completed.
- `S06`: divergence detection completed.
- `S07`: candidate metadata preparation completed with inference disabled.

The full opt-in test module reported 7 passed in 235.83 seconds.
The Phase 9 acceptance review found no failed command records.
The final reuse run confirmed `reused=1` for all six builder stages.
All 16 files in the two Docker artifact manifests matched their recorded sizes and SHA-256 checksums.

The saved divergence is in `sympy.algebras.quaternion:Quaternion.to_rotation_matrix`.
It identifies a changed return value at the expected return statement in `sympy/algebras/quaternion.py`.
The candidate preparation result records `inference: false` and a prompt length of 15,095 characters.
No model API call was required.

The validation environment was:

- Linux 5.15.0-139-generic on x86-64.
- Python 3.12.3.
- uv 0.10.0.
- Docker client and server 28.0.1.
- Docker API 1.48.

The current default test run still skips all seven real-data tests because they require Docker and SWE-bench resources.

The fixed test instance is `sympy__sympy-15349`.
The default real-test workspace is `.explainbench/real-tests/sympy-15349`.

The Phase 11 complete builder run enabled model inference for this instance.
It requested 10 changed candidates and 10 unchanged candidates from `gpt-5.2-2025-12-11` with medium reasoning effort.
All ten builder stages completed.
The published files loaded as one typed `LocalEffectContext` and one typed `AnswerGroundTruth`.
One `local.effect` evaluation completed with `gpt-5-mini-2025-08-07`.
The evaluation processed one task instance with no failure and produced a score of 1.
The repeated complete builder command reused all ten stages and made no second candidate request.

Canonical child commands use Python safe-path mode.
This prevents a package in the caller's current directory from shadowing the installed canonical package.
The change controls module resolution only.
It does not change canonical stage logic or relative data paths.

### Model persistence

Each candidate-generation attempt stores its complete prompt in `model-audit/prompt.txt` before inference.
Each exact raw model response is stored in `model-audit/responses/` before schema parsing.
`model-audit/manifest.json` records the model settings, schema name, file sizes, SHA-256 checksums, and selected response.
The attempt and status records link to this manifest.
The stage result also contains a checksummed artifact manifest and a source-response record.

On restart, the candidate stage checks prior attempts for a compatible prompt, model, reasoning effort, and response schema.
It verifies the saved response size and checksum before parsing.
It copies a valid response into the current attempt and does not make another model request.

If a received response cannot be stored, the model adapter does not retry the request.
The candidate command uses a dedicated exit status, and the stage marks this failure as non-retryable.
This prevents an automatic second paid request when durability is uncertain.

The scientific prompt template and Pydantic response parser are unchanged.

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

## Release requirements

The checker works without Docker, network access, or model credentials.
Evaluation requires access to the configured model provider.
The bundled evaluation configurations use OpenAI models and read `OPENAI_API_KEY`.

The complete local-effect builder requires:

- Python 3.12 or later.
- A working Docker service.
- Access to the configured source repository host.
- Access to Hugging Face for the configured SWE-bench dataset.
- Access to the Docker registries used by SWE-bench.
- Access and credentials for the configured candidate-generation model.

Start with at least 20 GB of free disk space.
The retained `sympy__sympy-15349` workspace uses 238 MiB after its Docker images are already present.
A clean Docker environment or a larger run can use much more space.

The retained one-instance Docker preparation took about four minutes.
The model-backed candidate and artifact stages took about four more minutes.
Runtime depends on image availability, network speed, model latency, and instance complexity.

The tracer supports optional serializers for target libraries such as Astropy, Django, pytest, scikit-learn, Sphinx, SymPy, and xarray.
These target libraries are not package requirements.
Their serializers activate when the traced target environment provides the matching library.

## Generated data and cleanup

Evaluation writes a result file and uses a checkpoint file during an incomplete resumable run.
A successful evaluation removes its checkpoint.

The builder workspace contains repositories, traces, logs, prompts, raw model responses, and checkpoints.
Treat the workspace as private data.
The public artifact output is a symbolic link to an immutable generation inside the workspace.
Copy the published artifact directory to durable storage before workspace cleanup.
Delete a workspace only after all builder processes stop and its resume and audit records are no longer required.

## Release automation

The extracted package contains three workflows under `.github/workflows`.
Fast tests and wheel-smoke tests run for pushes to `main` and for pull requests.
The real unpaid local-effect test is a manual Docker workflow.
These workflows become active when `explainbench-cli` becomes the root of its separate repository.

The CI environment uses Python 3.12 and the locked uv environment.
The real workflow does not enable candidate inference and does not require a model API key.

## Provisional release candidate

The confirmed distribution name is `explainbench`.
The confirmed first version is `0.1.0`.
The package author is `explainbench-team`.
The author email is `imamnurby@gmail.com`.
The project homepage is `https://explainbench.github.io`.

The current direct runtime dependencies use exact versions.
`uv.lock` records the complete environment.
The final unpinned direct dependency was `jsonpickle`.
It is now pinned to the locked version `4.1.2`.

The provisional wheel is `dist/explainbench-0.1.0-py3-none-any.whl`.
It contains 113 files.
Its SHA-256 is `197f08c3f9201fa38093aceaafc9d775f57a20f7c079d376fe3541c0a9e94a9b`.

The wheel contains the expected six top-level packages, eight runtime resources, console entry point, and pytest entry point.
It contains no tests, examples, logs, results, generated caches, or build directories.
The exact fast-CI command reported 142 passed and 7 skipped.
The exact wheel-smoke command reported 4 passed.
The complete local suite reported 146 passed and 7 skipped.

## Known package gaps

### Release blockers

- The package license decision is deferred.
- The new CI workflows have not run in the future separate repository.

### Validation gaps

- Python 3.14 installation has not been validated.
- Interruption, retry exhaustion, corruption, and semantic invalidation have not been validated with real external processes.
- The complete real workflow has not run from a non-editable wheel installation.

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

### Priority 1: Complete deferred license metadata

1. Initialize the separate repository.
2. Add the selected license and its package metadata.

### Priority 2: Run release automation

1. Run fast and wheel-smoke workflows in the separate repository.
2. Run the manual unpaid Docker workflow.
3. Build and inspect the final release candidate.

### Priority 3: Decide the end-to-end builder scope

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
