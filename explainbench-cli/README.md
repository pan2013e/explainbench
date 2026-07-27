# ExplainBench CLI

This repository contains the package-focused ExplainBench implementation.
The project website is [explainbench.github.io](https://explainbench.github.io).

The initial package extraction from the ExplainBench research repository is complete.
The package is ready for repository development and release-candidate validation.

## Installation

ExplainBench requires Python 3.12 or later.
Clone the repository and install the package:

```bash
git clone https://github.com/explainbench/explainbench-cli.git
cd explainbench-cli
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

### Runtime requirements

The checker does not require Docker, network access, or a model credential.
Evaluation requires network access to the configured model provider.
The bundled evaluation examples use OpenAI models and read `OPENAI_API_KEY`.

The complete local-effect builder requires:

- A working Docker service.
- Network access to Python package indexes during installation.
- Network access to the configured Git repository host.
- Network access to Hugging Face for the configured SWE-bench dataset.
- Network access to the Docker registries used by SWE-bench.
- Network access and credentials for the candidate-generation model provider.

Start with at least 20 GB of free disk space for Docker images, repositories, traces, and checkpoints.
The retained one-instance validation workspace used 238 MiB after the required Docker images were already present.
Actual disk use can be larger for a clean Docker environment or multiple instances.

The retained one-instance Docker preparation took about four minutes.
The model-backed candidate and artifact stages took about four more minutes.
First-time image builds, network speed, model latency, and instance complexity can increase these times.

### Optional target libraries

The tracer contains serializers for libraries such as Astropy, Django, pytest, scikit-learn, Sphinx, SymPy, and xarray.
These libraries are optional target-project integrations.
Do not install them only for ExplainBench.
The tracer uses an integration when the traced target environment provides that library.

### Generated files and cleanup

Evaluation writes its result file and may create a temporary checkpoint next to that file.
A successful evaluation removes its checkpoint.

The local-effect builder stores repositories, traces, logs, model prompts, raw model responses, and checkpoints under its workspace.
Treat this workspace as private build data.
The published output path is a symbolic link to an immutable generation inside the workspace.
Copy the published output to a separate durable directory before you delete the workspace.
Delete a workspace only when no builder process uses it and you no longer need its resume or audit data.

## Development and CI

Run the locked local test environment with:

```bash
uv sync --locked --dev
uv run pytest -ra
```

The repository includes three GitHub Actions workflows:

- Fast tests run on pushes and pull requests without clean-wheel or real Docker tests.
- Wheel smoke tests build and install the wheel in an isolated environment.
- Real local-effect validation is a manual unpaid Docker workflow.

The workflows run from the standalone `explainbench-cli` repository.

## Repository model

The source tree separates the CLI wrapper from the copied core modules:

```text
src/
├── explainbench/
└── core/
    ├── dataset/
    ├── execution/
    ├── tracer/
    └── tracer_plugin/
```

`src/core` is a repository container.
It is not a Python import package.

The wheel installs its children as the existing top-level packages:

- `dataset`
- `execution`
- `tracer`
- `tracer_plugin`

The CLI wrapper is available as `explainbench`.

## Current status

The `dataset`, `execution`, `explainbench`, `tracer`, and `tracer_plugin` packages are present.
Evaluation is implemented only under `explainbench.evaluation`.
The historical top-level `evaluation` compatibility package is not included.
The approved package examples and runtime resources are present.
All approved core modules have been copied.
The one-wheel package mapping and resource declarations are complete.
The final Phase 6 wheel passed archive and installed-package checks.
The complete suite reports 143 passed and 7 documented opt-in skips.
The standalone tracer inspector and serializer suites also pass.
Four clean-wheel tests cover the checker, resources, mocked evaluation, and the first local-builder stage with resume.
The opt-in real Docker sequence reports seven passes for scenarios `S01` through `S07`.
One complete model-backed local-effect workflow passed for `sympy__sympy-15349`.
The generated artifact passed typed evaluator loading and one real `local.effect` evaluation.
The repeated builder command reused all ten stages.
The sequence confirms artifact checksums and checkpoint reuse without a model API call.
Candidate inference now stores the complete prompt and each raw response before parsing.
Checksummed attempt records support audit and reuse after interruption.

One packaging adapter in `execution.util` builds the Docker tracer payload from the installed `tracer` and `tracer_plugin` packages.
This removes the old dependency on a sibling `py-tracer` repository directory.

See [EXPLAINBENCH_CLI_EXTRACTION_PLAN.md](EXPLAINBENCH_CLI_EXTRACTION_PLAN.md) for the implementation tracker.
See [CORE_PROVENANCE.md](CORE_PROVENANCE.md) for the copied-source record.
See [PACKAGE_HANDOFF.md](PACKAGE_HANDOFF.md) for current implementation and validation details.

## Development state

The package extraction and local validation are complete.
Do not publish a public package release until the license decision is complete and the release candidate passes the required CI workflows in this repository.
