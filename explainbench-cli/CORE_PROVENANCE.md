# Core Source Provenance

## Purpose

This file records the source of implementation files copied into the ExplainBench CLI package workspace.
Update this file whenever a core source path is copied or synchronized.

## Workspace

The package workspace is currently stored at `explainbench-cli/` inside the source research repository.
It is not a separate Git repository yet.
Yusuf owns the future `explainbench-cli` repository.

## Research repository source

Repository:
`https://github.com/pan2013e/explainbench.git`

Source revision:
`e71bfede8c099a98bbab3a6d8b0da61e7f52ed2d`

Revision date recorded:
2026-07-23

The research repository is the historical source for the initial extraction.
The scientific implementation must remain unchanged during copying.

### ExplainBench wrapper copy

Copied paths:

| Source | Target | Status |
|---|---|---|
| `src/explainbench` | `src/explainbench` | Copied unchanged |
| `examples` | `examples` | Eight approved files copied unchanged |

Verification:

- All 45 wrapper source and resource files matched their source files.
- All 8 approved example files matched their source files.
- Generated `__pycache__` directories were excluded.
- CLI help passed without the research source tree on `PYTHONPATH`.
- The lite and full examples passed the checker.
- The local stage registry listed ten expected stages.
- The focused wrapper test selection reported 31 passed.
- The wheel built without warnings and passed the same CLI checks from the wheel archive.

### Dataset core copy

Copied paths:

| Source | Target | Status |
|---|---|---|
| `dataset/__init__.py` | `src/core/dataset/__init__.py` | Copied unchanged |
| `dataset/extract_ground_truths/__init__.py` | `src/core/dataset/extract_ground_truths/__init__.py` | Copied unchanged |
| `dataset/extract_ground_truths/effect` | `src/core/dataset/extract_ground_truths/effect` | Initially copied, with recorded Phase 10 persistence adaptations |

Verification:

- All 17 copied files matched their source files.
- All 13 implementation modules imported from the copied package with unchanged source dependencies.
- Five build commands and two trace whitelist commands showed help successfully.
- The prompt template loaded from both the copied source tree and the wheel.
- The focused local-effect interface test reported 12 passed.
- The wheel built without warnings.
- Historical artifacts, explanation data, and agent patch collections were excluded.

Phase 10 approved these package-owned adaptations:

- `build_step2.py` stores and reuses candidate-inference audit records.
- `infer_expression.py` passes a raw-response callback to the model adapter.
- `audit_files.py` provides local atomic writes and SHA-256 checksums.
- `paid_inference.py` manages prompt, response, and selection records.
- `evaluation/inference.py` re-exports the persistence error through the legacy import path.

The prompt template, prompt construction, expression schema, and parsing call remain unchanged.

The selected `execution` package is still an external source dependency at this phase.
Repeat fully isolated dataset validation after it is copied.

### Legacy evaluation core copy

Copied paths:

| Source | Target | Status |
|---|---|---|
| `evaluation` | `src/core/evaluation` | Six compatibility modules copied unchanged |

Verification:

- All six copied files matched their source files.
- `infer_expression` imported with only the package workspace on `PYTHONPATH`.
- `evaluation.inference.Model` was the same object as `explainbench.evaluation.inference.Model`.
- The legacy evaluation command showed help.
- The compatibility test reported 3 passed.
- The wheel built without warnings.
- A clean Python 3.12 installation loaded the legacy package and dataset inference module from `site-packages`.

The existing dataset inference module opens its prompt through a filesystem path derived from `__file__`.
Normal wheel installation is supported and passed.
Direct import from the compressed `.whl` archive is not supported.

### Execution core copy

Copied paths:

| Source | Target | Status |
|---|---|---|
| Selected `execution` modules | `src/core/execution` | Copied |
| `execution/allowed_functions.json` | `src/core/execution/allowed_functions.json` | Copied unchanged |
| `execution/allowed_qualnames.json` | `src/core/execution/allowed_qualnames.json` | Copied unchanged |
| `execution/monkey_patch` | `src/core/execution/monkey_patch` | Four files copied unchanged |

Approved packaging adaptation:

- `execution.util.prepare_tracer()` no longer reads `execution/../py-tracer`.
- It locates the installed `tracer` and `tracer_plugin` packages.
- It archives those packages with the existing py-tracer project metadata.
- It preserves the `/root/py-tracer` Docker path and installation command.
- It excludes generated Python cache files.

Verification:

- Every execution file except the approved `util.py` adaptation matched its source.
- The three execution commands showed help successfully.
- All five copied core packages imported without a research repository fallback.
- All 13 dataset modules imported with only the package workspace on `PYTHONPATH`.
- Both whitelist resources loaded and each contained nine agent entries.
- The focused execution and local-effect test selection reported 27 passed.
- The generated tracer payload installed in a clean Python 3.12 environment.
- The payload provided `tracer`, `tracer_plugin`, and the pytest entry point.
- The complete wheel built without warnings.
- A clean wheel installation generated the tracer payload from `site-packages`.

## Tracer source

Repository:
`https://github.com/imamnurby/swe-bench-tracer-py.git`

Source revision:
`77f00f2e9f5669877443425a6e43b813d4c61a4b`

Copied paths:

| Source | Target | Status |
|---|---|---|
| `py-tracer/tracer` | `src/core/tracer` | Copied unchanged |
| `py-tracer/tracer_plugin` | `src/core/tracer_plugin` | Copied unchanged |

Verification:

- All 27 copied source files matched their source files.
- Generated `__pycache__` directories were excluded.
- Serializer validation reported 12 passed, 3 optional-dependency skips, and 0 failed.
- Inspector before-mode validation reported 17 passed.
- Inspector after-mode validation reported 17 passed.
- The serializer, pytest plugin, and Django plugin imported from the copied location.

## One-wheel packaging verification

The Phase 6 wheel uses explicit mappings for all copied packages.
It does not install `src/core` as an import package.

Verification:

- The wheel built without warnings.
- The wheel archive contains 111 files.
- All 15 required Python packages are present.
- All 8 required non-Python resources are present.
- Tests, logs, results, historical artifacts, research data, and generated caches are absent.
- The console entry point and tracer pytest entry point are present.
- A clean installed environment loaded all six top-level packages from `site-packages`.
- Python did not find an import package named `core`.
- Package metadata declares 15 direct runtime dependencies.

The dependency audit removed stale direct declarations for `asttokens`, `gitpython`, and `jq`.
The copied package does not import these libraries directly.
The `swebench` dependency still provides `gitpython` as a transitive dependency.
Builder dependencies remain in the default installation because the current command imports require them.

## Fast-test migration verification

The current package tests and opt-in real local-effect tests were copied into the extraction workspace.
Repository paths now use the extracted source layout.
Behavior assertions remain unchanged.

Verification:

- The complete pytest suite reported 135 passed and 7 skipped on Python 3.12.
- The source baseline was 132 passed and 7 skipped.
- Two extraction checksum tests and one tracer-payload regression test explain the three added passes.
- The seven skips are documented opt-in tests that require Docker and SWE-bench resources.
- The inspector before-mode program reported 17 passed.
- The inspector after-mode program reported 17 passed.
- The serializer program reported 12 passed, 3 optional-library skips, and 0 failed.
- The copied tracer programs retain their original source lines.

The inspector and serializer files run as standalone programs.
Their module names and source line numbers are test inputs.
The tracing input file also uses a non-pytest filename because its functions accept ordinary program arguments.

## Clean-wheel verification

Four integration tests build and install the wheel in an isolated Python 3.12 environment.
They run from a temporary directory outside the source repository.
They remove `PYTHONPATH` and disable user-site packages.

Verification:

- `explainbench --help` passed.
- `explainbench checker` validated the lite example.
- All 297 shared instance IDs loaded from the installed package.
- Both shared intent artifact pairs loaded from the installed package.
- Mocked lite evaluation completed for three instances.
- All ten local builder stages listed.
- The installed `dataset`, `execution`, and `tracer` packages loaded from `site-packages`.
- The canonical `identify-patched-functions` stage completed with local external inputs.
- Resume reused the first-stage checkpoint without a second canonical command.
- The complete suite reported 145 passed and 7 skipped after Phase 10.

## Paid-work persistence verification

Candidate-generation attempts now contain `model-audit/manifest.json`.
The attempt and status records link to this manifest.
The manifest records the full prompt, all raw responses, the selected response, file sizes, and SHA-256 checksums.

Verification:

- The prompt is written atomically before inference.
- Every raw response is written atomically before Pydantic parsing.
- A parsing failure leaves the exact raw response available for review.
- A simulated process interruption leaves a valid response available.
- A later attempt verifies and reuses that response without another model call.
- Parsed candidates identify their source response.
- A response-storage failure does not trigger a model retry.
- The stage marks the dedicated persistence failure as non-retryable.
- Real S07 prompt preparation passed with inference disabled.

## Complete real-workflow verification

Phase 11 ran the complete local-effect workflow for `sympy__sympy-15349`.
The run used the installed editable package and the retained real-test workspace.

Verification:

- The five existing Docker preparation stages reused their compatible checkpoints.
- Candidate generation requested 10 changed expressions and 10 unchanged expressions.
- Candidate generation used `gpt-5.2-2025-12-11` with medium reasoning effort.
- The audit journal stored one 15,105-byte prompt and one 731-byte raw response.
- Candidate execution, validation, answer-choice construction, and artifact publication completed.
- The published files loaded as one typed `LocalEffectContext` and one typed `AnswerGroundTruth`.
- One `local.effect` evaluation completed with `gpt-5-mini-2025-08-07`.
- The evaluator processed one instance with no failure and produced a score of 1.
- A repeated complete builder command reported `reused=1` for all ten stages.
- The repeated command did not make another candidate-generation request.

The first Phase 11 candidate command exposed a module-resolution conflict.
The child process loaded the research repository's stale top-level `dataset` package instead of the installed package.
The failure occurred before any model request.

The package wrapper now starts canonical Python modules with safe-path mode.
This prevents the current directory from shadowing installed canonical packages.
The change affects module resolution only.
It does not change canonical scientific logic or relative data paths.
A regression test covers the package-shadowing case.

## Release preparation verification

Phase 12 confirmed these package metadata values:

- Distribution name: `explainbench`.
- Version: `0.1.0`.
- Author: `explainbench-team`.
- Author email: `imamnurby@gmail.com`.
- Homepage: `https://explainbench.github.io`.

The remaining direct dependency without an exact version was `jsonpickle`.
It is now pinned to the locked version `4.1.2`.

Three GitHub Actions workflows are present:

- Fast tests for pushes and pull requests.
- Isolated wheel-smoke tests for pushes and pull requests.
- Manual unpaid real local-effect validation with Docker.

Verification:

- The exact fast-CI command reported 142 passed and 7 skipped.
- The exact wheel-smoke command reported 4 passed.
- The complete local suite reported 146 passed and 7 skipped.
- The provisional wheel contains 113 files.
- It contains all expected packages, resources, and entry points.
- It contains no tests, examples, logs, results, caches, or build directories.
- Its SHA-256 is `197f08c3f9201fa38093aceaafc9d775f57a20f7c079d376fe3541c0a9e94a9b`.

The license decision remains deferred until the separate repository is initialized.
The new workflows have not run in that separate repository.

## Ownership and synchronization

After extraction, the `explainbench-cli` repository is the source of truth for future packaged core changes.
The research repository can consume released package versions after extraction.
Do not maintain independent behavior changes in both repositories.

When a copied core file changes:

1. Make and validate the packaged change in `explainbench-cli`.
2. Record the change and its source revision in this file.
3. Release a package version.
4. Update the research repository to consume that package version when applicable.

## License

The package license decision is deferred until the separate Git repository is initialized.
Licensing must be complete before public distribution.
