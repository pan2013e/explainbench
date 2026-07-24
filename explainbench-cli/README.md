# ExplainBench CLI

This directory contains the package-focused ExplainBench implementation.

The package workspace is under active extraction from the ExplainBench research repository.
It is not release-ready yet.

## Installation

ExplainBench requires Python 3.12 or later.
Clone the repository and install the package from the `explainbench-cli` directory:

```bash
git clone https://github.com/pan2013e/explainbench.git
cd explainbench/explainbench-cli
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

Confirm that the command is available:

```bash
explainbench --help
```

For development, install the package in editable mode with its development dependencies:

```bash
python -m pip install -e .
python -m pip install "pytest>=8.4,<10"
```

## Usage

The CLI provides commands to validate submissions, evaluate explanations, and build local-effect question artifacts.
Run `explainbench --help` or add `--help` after a subcommand to see all available options.

### Validate a submission

Check the structure and contents of a submission JSON file:

```bash
explainbench checker submission.json
```

You can validate the bundled lite example without making model requests:

```bash
explainbench checker examples/submission-lite.json
```

### Evaluate explanations

Export the API credentials required by the model provider before you start an evaluation.
The bundled lite configuration evaluates the two intent tasks and writes the results under `results/`:

```bash
explainbench evaluate examples/submission-lite.json \
  --config examples/evaluation-lite.toml
```

This command makes paid model requests.
To select settings directly on the command line, use:

```bash
explainbench evaluate submission.json \
  --mode lite \
  --model MODEL_NAME \
  --num-generations 5 \
  --output results.json
```

Full evaluation also requires submission-specific question artifacts:

```bash
explainbench evaluate submission.json \
  --mode full \
  --model MODEL_NAME \
  --artifacts-dir question-artifacts \
  --output results.json
```

Add `--resume` to reuse compatible completed work after an interrupted evaluation.

### Build local-effect questions

List the available construction stages:

```bash
explainbench question-builder local stages
```

Run the complete local-effect pipeline:

```bash
explainbench question-builder local run submission.json \
  --workspace .explainbench/builds/my-agent \
  --output question-artifacts \
  --resume
```

The builder stores checkpoints, traces, and logs in the workspace directory.
Use the status command to inspect its progress:

```bash
explainbench question-builder local status \
  --workspace .explainbench/builds/my-agent
```

## Repository model

The source tree separates the CLI wrapper from the copied core modules:

```text
src/
├── explainbench/
└── core/
    ├── dataset/
    ├── evaluation/
    ├── execution/
    ├── tracer/
    └── tracer_plugin/
```

`src/core` is a repository container.
It is not a Python import package.

The wheel will install its children as the existing top-level packages:

- `dataset`
- `evaluation`
- `execution`
- `tracer`
- `tracer_plugin`

The CLI wrapper will remain available as `explainbench`.

## Current status

The `dataset`, `evaluation`, `execution`, `explainbench`, `tracer`, and `tracer_plugin` packages are present.
The approved package examples and runtime resources are present.
All approved core modules have been copied.
The one-wheel package mapping and resource declarations are complete.
The final Phase 6 wheel passed archive and installed-package checks.
The complete suite reports 145 passed and 7 documented opt-in skips.
The standalone tracer inspector and serializer suites also pass.
Four clean-wheel tests cover the checker, resources, mocked evaluation, and the first local-builder stage with resume.
The opt-in real Docker sequence reports seven passes for scenarios `S01` through `S07`.
The sequence confirms artifact checksums and checkpoint reuse without a model API call.
Candidate inference now stores the complete prompt and each raw response before parsing.
Checksummed attempt records support audit and reuse after interruption.

One packaging adapter in `execution.util` builds the Docker tracer payload from the installed `tracer` and `tracer_plugin` packages.
This removes the old dependency on a sibling `py-tracer` repository directory.

See [EXPLAINBENCH_CLI_EXTRACTION_PLAN.md](EXPLAINBENCH_CLI_EXTRACTION_PLAN.md) for the implementation tracker.
See [CORE_PROVENANCE.md](CORE_PROVENANCE.md) for the copied-source record.
See [PACKAGE_HANDOFF.md](PACKAGE_HANDOFF.md) for current implementation and validation details.

## Development state

Do not publish this package yet.
Model-backed validation, CI, licensing, and release metadata are incomplete.
