# ExplainBench CLI Repository Extraction Plan

## Document status

This document is the implementation plan and progress tracker for the proposed `explainbench-cli` repository.
It describes how to copy the required package implementation from the current research repository into a package-focused repository.

The current scientific implementation remains unchanged during extraction.
Extraction work is in progress under `explainbench-cli/`.

Plan date: 2026-07-23.

## Goal

Create a new repository that builds one self-contained ExplainBench wheel.

The new repository will:

- Preserve the existing scientific implementation.
- Preserve the Python import names required by the current CLI.
- Preserve the existing canonical module commands.
- Add the existing `explainbench` CLI and orchestration as a thin wrapper.
- Include only code and resources required by the package.
- Exclude historical data, generated files, and unrelated research projects.
- Support clean installation outside the research repository.

## Primary constraint

Do not redesign or duplicate the scientific implementation during extraction.

The first extraction must preserve:

- Function behavior.
- Prompt construction.
- Tracing behavior.
- Divergence behavior.
- Candidate generation behavior.
- Expression inspection behavior.
- Answer-choice behavior.
- Artifact export behavior.
- Public command behavior.
- Top-level import names used by current canonical modules.

The historical top-level `evaluation` compatibility package was initially preserved.
It was later removed because the separate package has no compatibility requirement for that old import path.
The current evaluator remains under `explainbench.evaluation`.

Changes are allowed only when they are required for:

- Packaging.
- Resource inclusion.
- Dependency declaration.
- Test relocation.
- Clean installation.
- Removal of a repository-path assumption that the CLI cannot satisfy with an explicit argument.

Any required behavior change must be recorded separately and must not be hidden inside a file move.

## Agreed repository model

The new repository will separate the CLI wrapper from copied core modules:

```text
explainbench CLI and orchestration
  -> copied canonical modules
  -> existing scientific functions
```

The repository will store the copied canonical modules under `src/core`.

`src/core` is a repository container only.
It is not a Python package.
It must not contain an `__init__.py` file.

The wheel will install the children of `src/core` as top-level packages:

| Source directory | Installed import package |
|---|---|
| `src/explainbench` | `explainbench` |
| `src/core/dataset` | `dataset` |
| `src/core/execution` | `execution` |
| `src/core/tracer` | `tracer` |
| `src/core/tracer_plugin` | `tracer_plugin` |

This mapping preserves imports such as:

```python
from dataset.extract_ground_truths.effect import build_step1
from explainbench.evaluation.inference import Model
from execution.util import get_instance_ids
from tracer.serializer import serialize
```

It also preserves module commands such as:

```bash
python -m dataset.extract_ground_truths.effect.build_step1
python -m execution.trace
```

## Target repository tree

The initial repository should have this complete structure:

```text
explainbench-cli/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── real-local-effect.yml
│       └── wheel-smoke.yml
├── examples/
│   ├── evaluation-full.toml
│   ├── evaluation-lite.toml
│   ├── submission-full.json
│   ├── submission-lite.json
│   └── question-artifacts/
│       ├── context/
│       │   ├── e2e_effect__example-full.json
│       │   └── local_effect__example-full.json
│       └── ground_truths/
│           ├── e2e_effect__example-full.json
│           └── local_effect__example-full.json
├── src/
│   ├── explainbench/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── checker.py
│   │   ├── cli.py
│   │   ├── resources.py
│   │   ├── schemas.py
│   │   ├── submission.py
│   │   ├── data/
│   │   │   ├── benchmark_instance_ids.json
│   │   │   ├── context/
│   │   │   │   ├── e2e_intent.json
│   │   │   │   └── local_intent.json
│   │   │   └── ground_truths/
│   │   │       ├── e2e_intent.json
│   │   │       └── local_intent.json
│   │   ├── evaluation/
│   │   │   ├── __init__.py
│   │   │   ├── artifacts.py
│   │   │   ├── checkpoints.py
│   │   │   ├── choices.py
│   │   │   ├── config.py
│   │   │   ├── inference.py
│   │   │   ├── predictions.py
│   │   │   ├── preparation.py
│   │   │   ├── registry.py
│   │   │   ├── results.py
│   │   │   ├── runner.py
│   │   │   ├── schemas.py
│   │   │   ├── scoring.py
│   │   │   ├── service.py
│   │   │   └── tasks.py
│   │   └── question_builders/
│   │       ├── __init__.py
│   │       ├── common/
│   │       │   ├── __init__.py
│   │       │   ├── artifacts.py
│   │       │   ├── atomic_files.py
│   │       │   ├── fingerprints.py
│   │       │   ├── locking.py
│   │       │   ├── orchestration.py
│   │       │   ├── status.py
│   │       │   └── subprocess_runner.py
│   │       └── local/
│   │           ├── __init__.py
│   │           ├── config.py
│   │           ├── publication.py
│   │           ├── registry.py
│   │           ├── runners.py
│   │           ├── service.py
│   │           ├── submission_adapter.py
│   │           └── workspace.py
│   └── core/
│       ├── dataset/
│       │   ├── __init__.py
│       │   └── extract_ground_truths/
│       │       ├── __init__.py
│       │       └── effect/
│       │           ├── __init__.py
│       │           ├── build_step1.py
│       │           ├── build_step2.py
│       │           ├── build_step3.py
│       │           ├── build_step4.py
│       │           ├── build_step5.py
│       │           ├── get_divergent_lines.py
│       │           ├── infer_expression.py
│       │           ├── postprocessing_util.py
│       │           ├── process_agent_patch.py
│       │           ├── source_util.py
│       │           ├── trace_step1_generate_qualname_whitelist.py
│       │           ├── trace_step2_generate_call_stack_whitelist.py
│       │           ├── trace_util.py
│       │           └── prompts/
│       │               └── template.txt
│       ├── execution/
│       │   ├── __init__.py
│       │   ├── allowed_functions.json
│       │   ├── allowed_qualnames.json
│       │   ├── inspect.py
│       │   ├── trace.py
│       │   ├── track.py
│       │   ├── util.py
│       │   └── monkey_patch/
│       │       ├── __init__.py
│       │       ├── inspect.py
│       │       ├── trace.py
│       │       └── track.py
│       ├── tracer/
│       │   ├── __init__.py
│       │   ├── inspector.py
│       │   ├── protocol.py
│       │   ├── tracer.py
│       │   ├── util.py
│       │   └── serializer/
│       │       ├── __init__.py
│       │       ├── _serializer.py
│       │       ├── util.py
│       │       └── ext/
│       │           ├── __init__.py
│       │           ├── astropy.py
│       │           ├── common.py
│       │           ├── django.py
│       │           ├── matplotlib.py
│       │           ├── numpy.py
│       │           ├── numpy_ext.py
│       │           ├── pandas.py
│       │           ├── pylint.py
│       │           ├── pytest.py
│       │           ├── sklearn.py
│       │           ├── sphinx.py
│       │           ├── stdlib.py
│       │           ├── sympy.py
│       │           └── xarray.py
│       └── tracer_plugin/
│           ├── __init__.py
│           ├── django_plugin.py
│           ├── pytest_plugin.py
│           └── sympy_plugin.py
├── tests/
│   ├── test_checker.py
│   ├── test_evaluate_cli.py
│   ├── test_evaluation_artifacts.py
│   ├── test_evaluation_config.py
│   ├── test_evaluation_inference.py
│   ├── test_evaluation_preparation.py
│   ├── test_evaluation_registry.py
│   ├── test_evaluation_results.py
│   ├── test_evaluation_runner.py
│   ├── test_evaluation_tasks.py
│   ├── test_examples.py
│   ├── test_legacy_evaluation_compat.py
│   ├── test_local_effect_cli_interfaces.py
│   ├── test_question_builder_canonical_commands.py
│   ├── test_question_builder_cli.py
│   ├── test_question_builder_orchestration.py
│   ├── test_resources.py
│   ├── test_submission.py
│   ├── real_local_effect/
│   │   ├── README.md
│   │   └── test_s01_s07_real_pipeline.py
│   ├── tracer/
│   │   ├── conf.py
│   │   ├── test_inspector_mode_after.py
│   │   ├── test_inspector_mode_before.py
│   │   ├── test_serializer.py
│   │   └── test_tracer.py
│   └── wheel/
│       ├── test_clean_checker.py
│       ├── test_clean_resources.py
│       ├── test_clean_evaluation.py
│       └── test_clean_local_builder.py
├── .gitignore
├── CORE_PROVENANCE.md
├── LICENSE
├── MANIFEST.in
├── PACKAGE_HANDOFF.md
├── README.md
├── pyproject.toml
└── uv.lock
```

## Initial scope

### Included

The first extraction includes:

- The current `src/explainbench` package.
- The local-effect modules under `dataset/extract_ground_truths/effect`.
- The local tracing and inspection modules under `execution`.
- The `tracer` package.
- The `tracer_plugin` package.
- Shared intent resources.
- Supported benchmark instance IDs.
- Existing package tests.
- Existing tracer tests.
- Existing local real-data tests.
- Small package examples.

### Excluded

The first extraction excludes:

- `audit_agent`.
- `pbt-generator`.
- `execution/pbt`.
- `execution/eval_wo_tracer.py`.
- Historical effect context files.
- Historical effect ground-truth files.
- `dataset/context/raw_pbts.json`.
- The explanation dataset and nested explanation repositories.
- Agent patch collections.
- Paper and supplementary files.
- Logs.
- Results.
- Build output.
- Distribution output.
- Egg metadata.
- Caches.

These exclusions can change only after a package workflow shows that one of these files is required.

## Current baseline

The source repository baseline is:

| Item | Current value |
|---|---|
| Branch | `package-own` |
| Fast tests | `132 passed, 7 skipped` |
| Real validation | `S01` and `S02` completed |
| Wheel build | Completes |
| Checker from wheel | Works with runtime dependencies available |
| Shared intent resources from wheel | All 297 instance IDs load |
| First local builder stage from wheel | Fails because `dataset` is absent |

Record the full source commit in `CORE_PROVENANCE.md` when extraction starts.
Do not use only a short commit ID in the provenance record.

## Status values

Each phase uses one of these values:

- `not_started`
- `in_progress`
- `blocked`
- `complete`

A phase is complete only when all required checks and acceptance criteria pass.

## Master tracker

| Phase | Name | Status | Exit condition |
|---:|---|---|---|
| 0 | Confirm extraction decisions | `complete` | Repository name, location, scope, and extraction ownership are confirmed. |
| 1 | Create the package workspace | `complete` | The package skeleton and provenance record exist. |
| 2 | Copy the `explainbench` wrapper package | `complete` | Checker, evaluator, and stage listing run from the new source tree. |
| 3 | Copy the dataset core | `complete` | All local-effect dataset modules import and their resources load. |
| 4 | Copy legacy evaluation core | `complete` | This historical copy was later removed under decision D015. |
| 5 | Copy execution and tracer core | `complete` | Track, trace, inspect, tracer, and plugins import successfully. |
| 6 | Configure one wheel | `complete` | The wheel contains every mapped package and required resource. |
| 7 | Migrate and pass fast tests | `complete` | All fast tests pass in the new repository. |
| 8 | Add clean-wheel tests | `complete` | Checker, resources, mocked evaluation, and the first builder stage pass outside the repository. |
| 9 | Run unpaid real validation | `complete` | Real scenarios `S01` through `S07` complete. |
| 10 | Add paid-work persistence | `complete` | Raw prompts and responses are durable and resumable. |
| 11 | Complete one real local-effect workflow | `complete` | A generated local-effect artifact was evaluated successfully. |
| 12 | Prepare release and handoff | `in_progress` | Technical release checks pass, and owner metadata remains open. |

## Phase 0: Confirm extraction decisions

Status: `complete`.

### Tasks

- [x] Confirm that the package will use a new repository.
- [x] Confirm that scientific behavior must remain unchanged.
- [x] Confirm that current top-level imports must remain unchanged.
- [x] Confirm that copied core modules will live under `src/core`.
- [x] Confirm that `src/core` is not an import namespace.
- [x] Define the initial included module set.
- [x] Define the initial excluded module set.
- [x] Confirm the final repository name as `explainbench-cli`.
- [x] Confirm the working directory as `explainbench-cli/` in the current repository.
- [x] Confirm Yusuf as the repository owner.
- [x] Confirm that nested Git initialization is deferred until the extraction is complete.
- [x] Defer the package license decision until Git repository initialization.
- [x] Confirm that `tracer` and `tracer_plugin` are copied into the wheel.
- [x] Confirm `explainbench-cli` as the source of truth for future packaged core changes.
- [x] Confirm that the research repository can consume released package versions after extraction.

### Acceptance criteria

- [x] Every deferred decision has an owner.
- [x] Every extraction decision has a recorded answer.
- [x] The extraction can continue without an unresolved code ownership issue.

## Phase 1: Create the package workspace

Status: `complete`.

### Tasks

- [x] Create the `explainbench-cli/` workspace.
- [x] Create the target directory skeleton.
- [x] Add `.gitignore`.
- [x] Add `README.md`.
- [x] Add `PACKAGE_HANDOFF.md`.
- [x] Add this extraction plan.
- [x] Add `CORE_PROVENANCE.md`.
- [x] Record the source repository URL.
- [x] Record the complete source commit.
- [x] Record every copied source path.
- [x] Add an initial `pyproject.toml`.
- [x] Add an initial `uv.lock`.
- [x] Record the baseline source revisions for copied implementation files.

### Acceptance criteria

- [x] The workspace has no generated build files.
- [x] The provenance file identifies the exact source revisions.
- [x] The workspace structure follows the approved plan.

## Phase 2: Copy the `explainbench` wrapper package

Status: `complete`.

### Source and target

| Source | Target | Action |
|---|---|---|
| `src/explainbench` | `src/explainbench` | Copy without implementation changes. |
| `examples` | `examples` | Copy only the listed package examples. |

### Tasks

- [x] Copy all non-generated files under `src/explainbench`.
- [x] Exclude all `__pycache__` directories.
- [x] Copy the four shared intent artifacts.
- [x] Copy `benchmark_instance_ids.json`.
- [x] Copy lite example files.
- [x] Copy full example files.
- [x] Confirm that every copied file matches its source.
- [x] Confirm that `python -m explainbench --help` works from the source tree.
- [x] Confirm that `explainbench checker` works from the source tree.
- [x] Confirm that `explainbench question-builder local stages` lists ten stages.

### Acceptance criteria

- [x] The wrapper package imports without the research repository on `PYTHONPATH`.
- [x] The checker validates the lite and full examples.
- [x] The stage registry lists the expected ten stage names.
- [x] No scientific core code is copied into `src/explainbench`.

## Phase 3: Copy the dataset core

Status: `complete`.

### Source and target

| Source | Target | Action |
|---|---|---|
| `dataset/__init__.py` | `src/core/dataset/__init__.py` | Copy unchanged. |
| `dataset/extract_ground_truths` | `src/core/dataset/extract_ground_truths` | Copy the local-effect implementation and prompt template. |

### Tasks

- [x] Copy every listed local-effect Python module.
- [x] Copy `prompts/template.txt`.
- [x] Exclude historical context and ground-truth files.
- [x] Exclude the explanation dataset.
- [x] Exclude agent patch collections.
- [x] Confirm that copied Python files match their sources.
- [x] Confirm that the prompt template matches its source.
- [x] Confirm that imports still use the `dataset` package name.
- [x] Confirm that `build_step1` through `build_step5` show help successfully.
- [x] Confirm that both trace whitelist commands show help successfully.

### Acceptance criteria

- [x] Every dataset module required by the ten stage wrappers imports with its unchanged source dependencies.
- [x] Prompt loading works from the copied location and wheel.
- [x] No historical model artifact is included.
- [x] No scientific source line changes during the copy.

## Phase 4: Copy the legacy evaluation core

Status: `complete`.

This phase records the initial extraction history.
Decision D015 later removed these compatibility-only files and redirected candidate generation to `explainbench.evaluation`.

### Source and target

| Source | Target | Action |
|---|---|---|
| `evaluation` | `src/core/evaluation` | Copy the six tracked compatibility modules. |

### Tasks

- [x] Copy `__init__.py`.
- [x] Copy `inference.py`.
- [x] Copy `main.py`.
- [x] Copy `schema.py`.
- [x] Copy `task.py`.
- [x] Copy `util.py`.
- [x] Confirm source equality.
- [x] Confirm that `dataset.extract_ground_truths.effect.infer_expression` imports.
- [x] Confirm that legacy evaluation compatibility tests pass.

### Acceptance criteria

- [x] Candidate generation can import `evaluation.inference.Model`.
- [x] Legacy imports remain unchanged.
- [x] The copied files match the source revision.

## Phase 5: Copy execution and tracer core

Status: `complete`.

### Source and target

| Source | Target | Action |
|---|---|---|
| Selected `execution` files | `src/core/execution` | Copy local-effect execution modules and resources. |
| `py-tracer/tracer` | `src/core/tracer` | Copy unchanged. |
| `py-tracer/tracer_plugin` | `src/core/tracer_plugin` | Copy unchanged. |

### Tasks

- [x] Copy `execution/__init__.py`.
- [x] Copy `execution/inspect.py`.
- [x] Copy `execution/trace.py`.
- [x] Copy `execution/track.py`.
- [x] Copy and adapt `execution/util.py` for the installed package layout.
- [x] Copy all four `execution/monkey_patch` files.
- [x] Copy `allowed_functions.json`.
- [x] Copy `allowed_qualnames.json`.
- [x] Copy all listed `tracer` files.
- [x] Copy all listed `tracer_plugin` files.
- [x] Confirm source file equality.
- [x] Confirm that `execution.track --help` works.
- [x] Confirm that `execution.trace --help` works.
- [x] Confirm that `execution.inspect --help` works.
- [x] Confirm that `tracer.serializer` imports.
- [x] Confirm that `tracer_plugin.pytest_plugin` imports.
- [x] Confirm that the Django plugin data loads.

### Acceptance criteria

- [x] Every execution module required by the local builder imports.
- [x] Every applicable tracer validation passes.
- [x] Default whitelist resources are present.
- [x] The tracer pytest entry point can load.
- [x] No scientific tracing or local-effect execution behavior changes.

## Phase 6: Configure one wheel

Status: `complete`.

### Package mapping

The package configuration must map:

```text
explainbench   -> src/explainbench
dataset        -> src/core/dataset
execution      -> src/core/execution
tracer         -> src/core/tracer
tracer_plugin  -> src/core/tracer_plugin
```

### Required Python packages

The wheel must include:

```text
explainbench
explainbench.evaluation
explainbench.question_builders
explainbench.question_builders.common
explainbench.question_builders.local
dataset
dataset.extract_ground_truths
dataset.extract_ground_truths.effect
execution
execution.monkey_patch
tracer
tracer.serializer
tracer.serializer.ext
tracer_plugin
```

### Required non-Python resources

The wheel must include:

```text
explainbench/data/benchmark_instance_ids.json
explainbench/data/context/e2e_intent.json
explainbench/data/context/local_intent.json
explainbench/data/ground_truths/e2e_intent.json
explainbench/data/ground_truths/local_intent.json
dataset/extract_ground_truths/effect/prompts/template.txt
execution/allowed_functions.json
execution/allowed_qualnames.json
```

### Tasks

- [x] Configure explicit package mappings.
- [x] Disable accidental namespace discovery for `src/core`.
- [x] Declare every required Python package.
- [x] Declare every required package-data file.
- [x] Preserve the `explainbench` console entry point.
- [x] Preserve the tracer pytest entry point.
- [x] Merge the `jsonpickle` dependency from `py-tracer`.
- [x] Review all current dependencies.
- [x] Retain builder dependencies as default dependencies because the current command imports require them.
- [x] Build the wheel.
- [x] Inspect the wheel file list.
- [x] Confirm that no `core/` directory appears in the installed import paths.
- [x] Confirm that no excluded research data appears in the wheel.

### Acceptance criteria

- [x] The wheel contains all required packages.
- [x] The wheel contains all required resources.
- [x] The wheel excludes tests, logs, results, historical artifacts, and research data.
- [x] The installed import names match the current import names.
- [x] The wheel metadata contains all runtime dependencies.

## Phase 7: Migrate and pass fast tests

Status: `complete`.

### Tasks

- [x] Copy current package tests.
- [x] Copy current real local-effect tests.
- [x] Copy tracer tests.
- [x] Update repository-path assertions to the new source layout.
- [x] Keep behavior assertions unchanged.
- [x] Add source-checksum tests for copied core files during extraction.
- [x] Run the complete fast suite.
- [x] Compare the result with the source baseline.
- [x] Investigate every new failure.
- [x] Record intentional test-count changes.

### Acceptance criteria

- [x] All fast tests pass.
- [x] No behavior assertion is weakened to make a copied module pass.
- [x] Every skipped test has a documented external requirement.
- [x] The test result is recorded in `PACKAGE_HANDOFF.md`.

## Phase 8: Add clean-wheel tests

Status: `complete`.

### Test environment

Each wheel test must:

1. Build the wheel.
2. Create a clean virtual environment.
3. Install the wheel and declared dependencies.
4. Change to a directory outside the source repository.
5. Remove the source repository from `PYTHONPATH`.
6. Run the selected command.

### Tasks

- [x] Add `test_clean_checker.py`.
- [x] Add `test_clean_resources.py`.
- [x] Add `test_clean_evaluation.py`.
- [x] Add `test_clean_local_builder.py`.
- [x] Confirm that `explainbench --help` works.
- [x] Confirm that `explainbench checker` works.
- [x] Confirm that all shared intent resources load.
- [x] Confirm that mocked lite evaluation works.
- [x] Confirm that all ten local stages list.
- [x] Confirm that `identify-patched-functions` completes.
- [x] Confirm that the first stage can resume without repeating work.

### Acceptance criteria

- [x] No test imports code from the source checkout.
- [x] No test depends on the source checkout as its current directory.
- [x] The current `ModuleNotFoundError: No module named 'dataset'` is fixed.
- [x] The first builder stage works only with installed wheel content and declared external services.

## Phase 9: Run unpaid real validation

Status: `complete`.

### Tasks

- [x] Run `S01` submission validation.
- [x] Run `S02` patched-function identification.
- [x] Run `S03` real test-call tracking.
- [x] Run `S04` trace-function selection.
- [x] Run `S05` detailed program tracing.
- [x] Run `S06` divergence detection.
- [x] Run `S07` candidate preparation with inference disabled.
- [x] Review every command record.
- [x] Review every external artifact checksum.
- [x] Confirm checkpoint reuse after every stage.
- [x] Record the test environment and Docker versions.

### Acceptance criteria

- [x] `S01` through `S07` complete from the new repository.
- [x] No model API call occurs in `S01` through `S07`.
- [x] Docker-backed outputs are durable and reusable.
- [x] The observed divergence is suitable for paid candidate generation.

## Phase 10: Add paid-work persistence

Status: `complete`.

This phase is a post-extraction improvement.
It must be committed separately from the copy-only extraction.

### Tasks

- [x] Persist the full candidate-generation prompt before inference.
- [x] Persist each raw model response before parsing.
- [x] Record file checksums.
- [x] Link prompt and response files from the stage attempt record.
- [x] Confirm that parsed candidates identify their source response.
- [x] Add interruption tests.
- [x] Add resume tests.
- [x] Confirm that completed paid responses are not requested again.

### Acceptance criteria

- [x] Paid inputs and outputs are auditable.
- [x] An interruption cannot lose a completed model response.
- [x] Resume can continue without repeating compatible paid requests.
- [x] Scientific prompt content and parsing behavior remain unchanged.

## Phase 11: Complete one real local-effect workflow

Status: `complete`.

### Tasks

- [x] Run model-backed candidate generation.
- [x] Review raw prompts and responses.
- [x] Execute candidate expressions.
- [x] Validate candidate expressions.
- [x] Build answer choices.
- [x] Export local-effect artifacts.
- [x] Load the generated artifacts with the evaluator.
- [x] Run `explainbench evaluate --task local.effect`.
- [x] Save the evaluation result.
- [x] Repeat the complete builder command with `--resume`.
- [x] Confirm that compatible Docker and model work is reused.

### Acceptance criteria

- [x] One real local-effect artifact is generated from the installed package.
- [x] The artifact passes typed evaluator validation.
- [x] The evaluator produces a result for the generated artifact.
- [x] Resume does not repeat compatible expensive work.

## Phase 12: Prepare release and handoff

Status: `in_progress`.

### Tasks

- [x] Add package description.
- [x] Add README metadata.
- [ ] Add license metadata.
- [x] Add authors.
- [x] Add project URLs.
- [x] Review the distribution name.
- [x] Review the package version.
- [x] Review exact dependency pins.
- [x] Document optional dependencies.
- [x] Document Docker requirements.
- [x] Document disk requirements.
- [x] Document network requirements.
- [x] Document model credentials.
- [x] Document expected runtime.
- [x] Document generated-file cleanup.
- [x] Add fast CI.
- [x] Add wheel-smoke CI.
- [x] Add opt-in real Docker CI or a manual workflow.
- [x] Update `PACKAGE_HANDOFF.md`.
- [x] Record source ownership and synchronization rules.
- [x] Build the release candidate.
- [x] Inspect the release candidate wheel.

### Acceptance criteria

- [x] A colleague can install and test the package from the documentation.
- [ ] The release candidate passes all required CI checks.
- [x] The wheel contains only intended files.
- [ ] The package has a clear license and owner.
- [x] The copied core has one documented source of truth.

## Migration manifest

| Current source | New target | Initial action | Tracker |
|---|---|---|---|
| `src/explainbench` | `src/explainbench` | Copy package files and resources. | [x] |
| `dataset/__init__.py` | `src/core/dataset/__init__.py` | Copy unchanged. | [x] |
| `dataset/extract_ground_truths` | `src/core/dataset/extract_ground_truths` | Copy the listed local-effect files. | [x] |
| `evaluation` | Removed | Initially copy, then remove the compatibility-only package. | [x] |
| Selected `execution` files | `src/core/execution` | Copy local-effect execution files and resources. | [x] |
| `py-tracer/tracer` | `src/core/tracer` | Copy unchanged. | [x] |
| `py-tracer/tracer_plugin` | `src/core/tracer_plugin` | Copy unchanged. | [x] |
| Package tests | `tests` | Copy and update source-path checks. | [x] |
| Tracer tests | `tests/tracer_tests` | Copy and preserve behavior assertions. | [x] |
| Package examples | `examples` | Copy the listed small examples. | [x] |
| `PACKAGE_HANDOFF.md` | `PACKAGE_HANDOFF.md` | Copy and update repository context. | [x] |
| `README.md` | `README.md` | Rewrite for package installation and use. | [x] |

## Exclusion manifest

| Source | Reason for exclusion | Reconsider when |
|---|---|---|
| `audit_agent` | No current package command depends on it. | An audit command becomes part of the supported CLI. |
| `pbt-generator` | It is a large independent project. | End-to-end question building is implemented. |
| `execution/pbt` | The current package consumes staged end-to-end artifacts. | End-to-end artifact generation moves into package scope. |
| Historical effect artifacts | They belong to historical submissions. | A small file is selected as a test fixture. |
| Explanation data | It is large research data. | A specific small runtime resource is proven necessary. |
| `supplementary_materials` | It is not runtime package content. | Never for the wheel. |
| Logs and results | They are generated output. | Never for the wheel. |
| Build and distribution directories | They are generated output. | Never for source control. |
| Egg metadata | It is generated package metadata. | Never for source control. |

## Validation matrix

| Capability | Source baseline | New source tree | Clean wheel | Real external run |
|---|---:|---:|---:|---:|
| CLI help | Pass | Pass | Pass | Not required |
| Submission checker | Pass | Pass | Pass | Pass |
| Shared intent loading | Pass | Pass | Pass | Not required |
| Mocked lite evaluation | Pass | Pass | Pass | Not required |
| Mocked full evaluation | Pass | Pass | Not tested | Not required |
| Local stage listing | Pass | Pass | Pass | Not required |
| Patched-function identification | Pass in repository | Pass | Pass | Pass |
| Docker call tracking | Not completed | Pass | Not tested | Pass |
| Docker detailed tracing | Not completed | Pass | Not tested | Pass |
| Divergence detection | Not completed on current real case | Pass | Not tested | Pass |
| Prompt-only candidate preparation | Not completed on current real case | Pass | Not tested | Pass |
| Paid candidate generation | Not validated | Pass | Not tested | Pass |
| Expression inspection | Not validated | Pass | Not tested | Pass |
| Artifact publication | Fast-test only | Pass | Not tested | Pass |
| Generated artifact evaluation | Not validated | Pass | Not tested | Pass |
| Resume after interruption | Fast-test only | Pass | Not tested | Not tested |

## Risk register

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| Copied core diverges from the research repository | Scientific behavior can differ between repositories. | Select one owner and document one synchronization direction. | Closed |
| A required transitive module is omitted | Clean-wheel imports fail. | Add import and wheel-content tests for every canonical stage. | Open |
| A non-Python resource is omitted | A stage fails after installation. | Maintain the required resource manifest and inspect the wheel. | Closed |
| A repository-relative path remains | A command works only from a checkout. | Run every clean-wheel test outside the source directory. | Open |
| The `core` directory becomes an import namespace | Existing imports break. | Do not add `src/core/__init__.py`; use explicit package mappings. | Closed |
| Tracer plugin registration changes | Docker test execution can change. | Preserve and test the pytest entry point. | Closed |
| Licenses are incompatible or incomplete | Distribution cannot be released safely. | Resolve licensing before copying core into a release branch. | Open |
| Historical data enters the wheel | The wheel becomes large and submission-specific. | Use explicit package and resource manifests. | Closed |
| Test assertions are weakened during relocation | Behavior changes can be hidden. | Permit path-only test changes and review all assertion changes. | Open |
| Paid inference runs before durability exists | Model work can be lost or repeated. | Complete Phase 10 before Phase 11. | Closed |

## Decision log

| ID | Decision | Status | Date |
|---|---|---|---|
| D001 | Use a separate package-focused repository. | Agreed | 2026-07-23 |
| D002 | Preserve the existing scientific implementation during extraction. | Agreed | 2026-07-23 |
| D003 | Store copied core modules under `src/core`. | Agreed | 2026-07-23 |
| D004 | Keep `core` out of Python import names. | Agreed | 2026-07-23 |
| D005 | Preserve `dataset`, `evaluation`, `execution`, `tracer`, and `tracer_plugin` import names. | Superseded by D015 | 2026-07-23 |
| D006 | Build one wheel containing the wrapper and required core modules. | Agreed | 2026-07-23 |
| D007 | Exclude `audit_agent` and `pbt-generator` from the first extraction. | Agreed | 2026-07-23 |
| D008 | Copy tracer into the wheel instead of using a separate dependency. | Agreed | 2026-07-23 |
| D009 | Make the new repository the owner of future packaged core changes. | Agreed | 2026-07-23 |
| D010 | Use `explainbench-cli` as the final repository name. | Agreed | 2026-07-23 |
| D011 | Build under `explainbench-cli/` in the current repository and defer nested Git initialization. | Agreed | 2026-07-23 |
| D012 | Set Yusuf as the owner of the future `explainbench-cli` repository. | Agreed | 2026-07-23 |
| D013 | Defer the package license decision until Git repository initialization. | Agreed | 2026-07-23 |
| D014 | Let the research repository consume released package versions after extraction. | Agreed | 2026-07-23 |
| D015 | Remove the compatibility-only top-level `evaluation` package and use `explainbench.evaluation` directly. | Agreed | 2026-07-24 |

## Progress log

### 2026-07-23: Copy tracer packages

Phase: 5

Completed: Copied `py-tracer/tracer` and `py-tracer/tracer_plugin` unchanged into `explainbench-cli/src/core/`.

Checks: Source equality passed.
The copied imports passed.
The serializer script reported 12 passed, 3 skipped, and 0 failed.
The before-mode inspector script reported 17 passed.
The after-mode inspector script reported 17 passed.

Problems: Direct pytest collection is not a valid full-suite command for the current tracer tests.
It collects trace-target functions as tests, changes expected `__main__` serialization names, and requires optional libraries that are not installed.

Decisions: Bundle `tracer` and `tracer_plugin` in the ExplainBench CLI wheel.

Next action: Create the remaining Phase 1 package workspace files.

### 2026-07-23: Complete the package workspace

Phase: 0 and 1

Completed: Confirmed package ownership, created the workspace files, recorded source provenance, added initial package metadata, and generated `uv.lock`.

Checks: Phase 0 decisions are complete.
The tracer-only wheel built successfully.
The wheel contained `tracer`, `tracer.serializer`, `tracer.serializer.ext`, and `tracer_plugin`.
A clean Python 3.12 environment imported `tracer` and `tracer_plugin` from `site-packages`.
The installed metadata contained the `tracer_plugin.pytest_plugin` entry point.

Problems: The license remains intentionally deferred until Git repository initialization.

Decisions: `explainbench-cli` owns future packaged core changes.
The research repository can consume released package versions after extraction.

Next action: Copy the existing `src/explainbench` wrapper package in Phase 2.

### 2026-07-23: Copy the ExplainBench wrapper

Phase: 2

Completed: Copied 45 wrapper source and resource files and 8 approved example files without implementation changes.
Updated package mappings, the CLI entry point, resource inclusion, dependencies, and the lock file.

Checks: Source equality passed.
The CLI help command passed from the new source tree.
The lite and full example submissions passed the checker.
The local stage registry listed the expected ten stages.
The focused wrapper test selection reported 31 passed.
The wheel built without warnings.
The same CLI checks passed when Python loaded `explainbench` directly from the wheel archive.

Problems: The canonical `dataset`, `evaluation`, and `execution` packages are still absent.
Commands that execute scientific builder stages remain incomplete until Phases 3 through 5 finish.

Decisions: Keep the wrapper implementation unchanged and use explicit package mappings for its installed import name.

Next action: Copy the selected dataset core in Phase 3.

### 2026-07-23: Copy the dataset core

Phase: 3

Completed: Copied 17 approved dataset package files without implementation changes.
Added the `dataset` package mapping and prompt resource configuration.

Checks: Source equality passed.
All 13 implementation modules imported from the copied package.
The five build commands and two trace whitelist commands showed help successfully.
The prompt loaded from the copied source tree and wheel.
The focused local-effect interface test reported 12 passed.
The wheel built without warnings.

Problems: Dataset imports still require the legacy `evaluation` and selected `execution` packages.
The compatibility checks used the unchanged research versions of those dependencies.
Fully isolated dataset validation must run again after Phases 4 and 5.

Decisions: Include only the local-effect implementation and its prompt.
Exclude all historical artifacts, explanation data, and agent patch collections.

Next action: Copy the legacy evaluation core in Phase 4.

### 2026-07-23: Copy the legacy evaluation core

Phase: 4

Completed: Copied all six legacy evaluation compatibility modules without implementation changes.
Added the top-level `evaluation` package mapping.

Checks: Source equality passed.
`infer_expression` imported with only the package workspace on `PYTHONPATH`.
The legacy and canonical `Model` objects were identical.
The legacy evaluation command showed help.
The compatibility test reported 3 passed.
The wheel built without warnings.
A clean Python 3.12 installation loaded `evaluation` and `infer_expression` from `site-packages`.

Problems: Direct import from the compressed wheel archive does not support the existing `__file__`-based prompt open in `infer_expression`.
Normal wheel installation extracts the file and passed.

Decisions: Preserve the existing prompt-loading implementation.
Test installed wheels instead of treating the compressed wheel as a Python path.

Next action: Copy the selected execution modules and resources in Phase 5.

### 2026-07-23: Complete execution and tracer extraction

Phase: 5

Completed: Copied 11 approved execution files and resources.
Added the `execution` package mapping and both JSON resources.
Replaced one repository-relative tracer payload lookup with an installed-package adapter.
Added a regression test for the generated Docker tracer payload.

Checks: All unchanged execution files matched their sources.
The three execution commands showed help.
All five copied top-level core packages imported without a research repository fallback.
All 13 dataset modules imported in the isolated package workspace.
Both whitelist resources loaded and each contained nine agent entries.
The focused execution and local-effect test selection reported 27 passed.
The tracer payload regression test passed.
The generated payload installed in a clean Python 3.12 environment.
Its `tracer`, `tracer_plugin`, and pytest entry point loaded successfully.
The complete Phase 5 wheel built without warnings.
A clean wheel installation loaded all five core packages from `site-packages`.
The installed package generated a complete tracer payload.

Problems: The original `prepare_tracer()` required a sibling `py-tracer` repository directory.
That directory does not exist after normal wheel installation.

Decisions: Build the Docker tracer payload from the installed `tracer` and `tracer_plugin` packages.
Keep the existing `/root/py-tracer` container path and installation command unchanged.

Next action: Complete and inspect the one-wheel configuration in Phase 6.

Date: 2026-07-23.

Phase: 6.

Completed: Configured one explicit wheel for all six top-level import packages.
Declared all required resources, the console entry point, the pytest entry point, and 15 direct runtime dependencies.
Removed the stale direct declarations for `asttokens`, `gitpython`, and `jq`.
The `swebench` dependency still provides `gitpython` as a transitive dependency.
Retained builder dependencies as default dependencies because the current command imports require them.

Checks: The final wheel built without warnings and passed its archive integrity check.
The wheel contains 111 files, all 15 required Python packages, and all 8 required resources.
The wheel does not contain `core`, tests, logs, results, historical artifacts, research data, or generated caches.
A clean installed environment loaded all six top-level packages from `site-packages`.
Python did not find an import package named `core`.
The installed metadata contains 15 direct runtime dependencies.
The console entry point, pytest entry point, and execution command help checks passed.

Problems: No Phase 6 blocker remains.

Decisions: Use explicit package mappings and explicit package-data declarations.
Keep the builder dependencies in the default installation until command imports can be made lazy without changing default behavior.

Next action: Migrate and pass the fast tests in Phase 7.

Date: 2026-07-23.

Phase: 7.

Completed: Copied the package tests, opt-in real local-effect tests, and tracer test programs.
Updated repository paths for the extracted layout without changing behavior assertions.
Added two extraction checks for unchanged core files and the recorded execution packaging adapter.
Added pytest as a development dependency.

Checks: The complete pytest suite reported 135 passed and 7 skipped on Python 3.12.
The source baseline was 132 passed and 7 skipped.
The three added passing tests are two extraction checksum tests and the tracer-payload regression test.
The inspector before-mode program reported 17 passed.
The inspector after-mode program reported 17 passed.
The serializer program reported 12 passed, 3 optional-dependency skips, and 0 failed.

Problems: Pytest initially treated `tests/tracer` as the installed `tracer` package.
Renaming the test directory to `tests/tracer_tests` removed that namespace collision.
The tracer source programs require standalone execution because their module name and source line numbers are test inputs.
The serializer socket test requires permission to create a local socket.

Decisions: Preserve the tracer programs unchanged under non-pytest filenames.
Run the inspector and serializer validations as documented standalone suites.
Keep the seven real local-effect tests opt-in because they require Docker and SWE-bench resources.

Next action: Add automated clean-wheel tests in Phase 8.

Date: 2026-07-23.

Phase: 8.

Completed: Added four clean-wheel integration tests with one session-scoped isolated installation.
The tests build the wheel, create a Python 3.12 environment, install all declared dependencies, remove `PYTHONPATH`, disable user-site packages, and run commands from a temporary directory outside the repository.

Checks: All four clean-wheel tests passed.
The installed CLI help and checker commands passed.
All 297 shared instance IDs and both shared intent artifact pairs loaded.
Mocked lite evaluation completed for three submission instances.
All ten local builder stages listed.
The installed `dataset`, `execution`, and `tracer` packages loaded from `site-packages`.
The canonical `identify-patched-functions` stage completed with a local dataset and local Git repository.
The resumed stage reused its checkpoint and did not create a second command record.
The complete suite reported 139 passed and 7 skipped.

Problems: No Phase 8 blocker remains.

Decisions: Share one clean installation across the four integration tests to keep the suite practical.
Use local test inputs for the first canonical stage so the test does not require Docker, network access, or a model API.

Next action: Run unpaid real validation in Phase 9.

Date: 2026-07-23.

Phase: 9.

Completed: Ran real scenarios `S01` through `S07` from the extracted package with the fixed `sympy__sympy-15349` instance.
Ran `S07` again after completion to confirm reuse for all six builder stages.

Checks: The full opt-in module reported 7 passed in 235.83 seconds.
The separate initial `S03` run reported 1 passed in 181.75 seconds.
The final `S07` reuse run reported 1 passed in 16.22 seconds.
All 36 saved command records have exit status zero.
All six stage checkpoints reported `reused=1` in the final run.
All 16 external files in the tracking and tracing manifests matched their saved sizes and SHA-256 checksums.
Candidate inference was disabled, the result records `inference: false`, and the prepared prompt length is 15,095 characters.
The divergence is in `sympy.algebras.quaternion:Quaternion.to_rotation_matrix` at the expected return statement.
The environment used Linux 5.15.0-139-generic, Python 3.12.3, uv 0.10.0, Docker client and server 28.0.1, and Docker API 1.48.

Problems: An initial environment setup selected Python 3.14 and could not build `orjson` because no Rust toolchain was configured.
The validation environment was recreated with the supported and previously tested Python 3.12 interpreter.
No Phase 9 blocker remains.

Decisions: Keep real Docker validation opt-in.
Use the retained workspace to verify that checkpoints remain reusable after package extraction.
Do not start paid inference until Phase 10 stores raw prompts and raw model responses.

Next action: Add paid-work persistence in Phase 10.

Date: 2026-07-24.

Phase: 10.

Completed: Added an atomic candidate-inference journal to each stage attempt.
The journal stores the full prompt before inference and stores every exact raw response before schema parsing.
It records file sizes and SHA-256 checksums.
The attempt and status records link to `model-audit/manifest.json`.
The completed stage result contains a checksummed artifact manifest and identifies the raw response used for parsed candidates.

Checks: The paid-persistence tests cover exact prompt and response storage, parsing failure, process interruption, compatible response reuse, and storage failure.
The interruption test confirms that restart parses the saved response without another inference call.
The persistence-failure test confirms that the model adapter does not retry and that the stage disables automatic retry.
The final complete suite reported 145 passed and 7 skipped.
The real S07 prompt-only scenario passed with inference disabled.
Its real prompt and audit manifest passed checksum validation.

Problems: The first complete run found one old CLI test double that did not create the required audit record.
The test double now creates the same prompt, response, and source link as the candidate stage.
No Phase 10 blocker remains.

Decisions: Keep prompt construction and Pydantic parsing in the canonical dataset modules.
Use one audit directory per stage attempt.
Copy a compatible prior response into the current attempt before parsing it.
Use a dedicated process exit status when a received response cannot be stored, and do not retry that failure automatically.

Next action: Complete one real model-backed local-effect workflow in Phase 11.

Date: 2026-07-24.

Phase: 11.

Completed: Ran the complete local-effect builder for `sympy__sympy-15349` with model-backed candidate generation.
The candidate request used `gpt-5.2-2025-12-11`, medium reasoning effort, 10 changed candidates, and 10 unchanged candidates.
The workflow executed and validated the candidates, built answer choices, and published evaluator artifacts.
Loaded the published files as one typed `LocalEffectContext` and one typed `AnswerGroundTruth`.
Ran one `local.effect` evaluation with `gpt-5-mini-2025-08-07`.
Saved the evaluation result under the retained real-test workspace.
Repeated the complete builder command with `--resume`.

Checks: The candidate audit contains a 15,105-byte prompt and one 731-byte raw response.
The prompt, response, audit manifest, stage result, and published files have recorded SHA-256 checksums.
All ten builder stages completed.
The repeated builder command reported `reused=1` for every stage and made no second candidate request.
Typed evaluator loading found one context and one ground truth for `sympy__sympy-15349`.
The evaluator processed one task instance with no failure and produced a score of 1.
The evaluator used 996 prompt tokens and 723 completion tokens.
The final complete suite reported 146 passed and 7 skipped.

Problems: The first paid-stage attempt loaded the stale research-repository `dataset` package from the current directory.
The child command failed before any model request because that module did not support the new audit options.
Canonical child commands now use Python safe-path mode so the current directory cannot shadow the installed package.
A regression test reproduces this package-shadowing case.
The first complete test run could not download isolated wheel-build requirements because network access was restricted.
The same suite passed when network access was allowed.

Decisions: Keep canonical command data paths relative to the caller workspace.
Use Python safe-path mode only to control module resolution.
Retain the real builder workspace, model audit, published artifact generation, and evaluation result as Phase 11 evidence.

Next action: Prepare release metadata, documentation, automation, and the release candidate in Phase 12.

Date: 2026-07-24.

Phase: 12.

Completed: Added a release-focused package description.
Pinned the remaining unpinned direct dependency, `jsonpickle`, to the locked version `4.1.2`.
Documented Docker, disk, network, credentials, runtime, optional target libraries, generated data, and cleanup requirements.
Added fast-test, wheel-smoke, and manual unpaid real-Docker GitHub Actions workflows.
Updated the package handoff with current release status and removed completed Phase 11 gaps.
Built and inspected the provisional `0.1.0` wheel.

Checks: All three workflow files passed YAML parsing.
The locked installation command completed.
The exact fast-CI command reported 142 passed and 7 skipped.
The exact wheel-smoke command reported 4 passed.
The complete local suite remains 146 passed and 7 skipped.
The wheel contains 113 files and has SHA-256 `197f08c3f9201fa38093aceaafc9d775f57a20f7c079d376fe3541c0a9e94a9b`.
The wheel contains the expected `dataset`, `evaluation`, `execution`, `explainbench`, `tracer`, and `tracer_plugin` packages.
It contains the expected resources, console entry point, and pytest entry point.
It contains no tests, examples, logs, results, generated caches, or build directories.

Problems: The license decision remains deferred.
The workflows cannot run on GitHub until `explainbench-cli` becomes the root of its separate repository.
The manual Docker workflow has not run on a GitHub-hosted runner.

Decisions: Use `explainbench` as the distribution name and `0.1.0` as the first version.
Use `explainbench-team` and `imamnurby@gmail.com` as the package author.
Use `https://explainbench.github.io` as the project homepage.
Keep direct runtime dependencies exact for the current application-style release.
Keep model-backed tests out of CI.
Use a manual unpaid workflow for real Docker validation.
Keep license work deferred until repository initialization, as requested by the owner.

Next action: Initialize the separate repository, add the license, and run the new workflows.

Date: 2026-07-24.

Phase: Post-extraction compatibility cleanup.

Completed: Removed the historical top-level `evaluation` compatibility package.
Removed the unused internal `explainbench.evaluation.legacy` facade.
Changed candidate generation to import `Model` and `InferencePersistenceError` directly from `explainbench.evaluation.inference`.
Removed the legacy package mappings and three compatibility-only tests.
Updated clean-wheel coverage and package documentation.

Checks: The focused evaluator, candidate, builder, and source-integrity selection reported 87 passed.
The complete non-wheel suite reported 139 passed and 7 skipped.
The isolated wheel suite reported 4 passed.
The complete suite therefore reports 143 passed and 7 skipped.
The isolated wheel confirms that top-level `evaluation` is absent.
It also confirms that candidate generation uses the current `explainbench.evaluation.Model` object.
The real unpaid S07 candidate-preparation scenario passed in 376.84 seconds with the package CLI.
The wheel contains 106 files and has SHA-256 `3fd6edbd3753171d4795c43e627f8c498c6ca3529d4987bdb66586daf07c3e6b`.
The wheel contains the expected `dataset`, `execution`, `explainbench`, `tracer`, and `tracer_plugin` packages.

Problems: Code that imports the historical top-level `evaluation` package is no longer compatible.
The current CLI did not use that API.
The first real-test command selected an outer repository executable from `PATH`.
The real-test fixture now prefers the executable beside its active Python interpreter and uses `PATH` only as a fallback.

Decisions: Keep all current evaluator implementation under `explainbench.evaluation`.
Do not retain compatibility-only import packages in the separate distribution.
Do not change evaluator, question-builder, execution, or tracer behavior.

Next action: Add the deferred license and run CI from the separate repository.

## Progress log template

Add one entry after each work session:

```text
Date:
Phase:
Completed:
Checks:
Problems:
Decisions:
Next action:
```

## Immediate next step

Phase 0 is complete.

Phase 1 is complete.

Phase 2 is complete.

Phase 3 is complete.

Phase 4 is complete.

Phase 5 is complete.

Phase 6 is complete.

Phase 7 is complete.

Phase 8 is complete.

Phase 9 is complete.

Phase 10 is complete.

Phase 11 is complete.

Phase 12 is in progress.

Add the deferred license and run CI from the separate repository.
