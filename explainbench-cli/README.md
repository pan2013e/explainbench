# ExplainBench CLI

This directory contains the package-focused ExplainBench implementation.

The package workspace is under active extraction from the ExplainBench research repository.
It is not release-ready yet.

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
The complete suite reports 139 passed and 7 documented opt-in skips.
The standalone tracer inspector and serializer suites also pass.
Four clean-wheel tests cover the checker, resources, mocked evaluation, and the first local-builder stage with resume.

One packaging adapter in `execution.util` builds the Docker tracer payload from the installed `tracer` and `tracer_plugin` packages.
This removes the old dependency on a sibling `py-tracer` repository directory.

See [EXPLAINBENCH_CLI_EXTRACTION_PLAN.md](EXPLAINBENCH_CLI_EXTRACTION_PLAN.md) for the implementation tracker.
See [CORE_PROVENANCE.md](CORE_PROVENANCE.md) for the copied-source record.
See [PACKAGE_HANDOFF.md](PACKAGE_HANDOFF.md) for current implementation and validation details.

## Development state

Do not publish this package yet.
CI, real Docker validation, licensing, and release metadata are incomplete.
