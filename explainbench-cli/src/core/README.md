# Core implementation changes

## Purpose

This file explains how the code in `src/core` differs from the code on the `main` branch of the original ExplainBench repository.
It is for maintainers who need to understand which parts were copied without changes and which parts were changed for the command-line package.

This review used `main` commit `5d146b138b46` as the comparison point.
The package source was at commit `5a112a7329c5` when this review was written.

## Source layout

`src/core` is a source container.
It is not an importable Python package.

The wheel installs its child directories with their existing import names:

```text
src/core/dataset/        -> dataset
src/core/execution/      -> execution
src/core/tracer/         -> tracer
src/core/tracer_plugin/  -> tracer_plugin
```

The command-line wrapper is in `src/explainbench`.
The wrapper imports and runs the modules from `src/core`.

## Summary

The current implementation keeps most of the original calculation and trace logic.
The changes are not limited to command-line argument parsing.

The current implementation also changes these parts of the run:

- Input and output paths can be set by the caller.
- Worker counts, retry counts, timeouts, and model settings can be set by the caller.
- Some old incremental output and result reuse behavior was removed or changed.
- Models and the SWE-bench dataset are loaded only when they are needed.
- Execution commands can use a selected work directory and report directory.
- Trace commands can use a selected function whitelist.
- The installed wheel can build the tracer files that the Docker run needs.

Most new options use the old fixed values as their defaults.
The default calculation results should usually be the same.
Run control, file placement, and result reuse can still differ from `main`.

## Dataset changes

The files under `dataset/extract_ground_truths/effect` build the local-effect question data.

### Files copied without calculation changes

The following files match `main`:

- `get_divergent_lines.py`
- `postprocessing_util.py`
- `process_agent_patch.py`
- `source_util.py`
- `trace_util.py`
- `prompts/template.txt`

The package also adds `dataset/__init__.py` so that the wheel can install `dataset` as a Python package.

### `trace_step1_generate_qualname_whitelist.py`

The code that finds changed qualified names is unchanged.
The caller can now set the agent list, prediction file, dataset, repository remote, instance filter, and output path.

### `trace_step2_generate_call_stack_whitelist.py`

The code that reads call data and selects qualified names is unchanged.
The caller can now set the agent list, instance filter, and input and output paths.

### `build_step1.py`

The first-divergence calculation is unchanged.
The caller can now set the trace directory, timeout, worker count, selected agents, selected instances, and output paths.

The old code could read an existing output file and skip agents that were already present.
The current code builds the selected output for the current run and writes it to the requested path.
This is a change to restart and result reuse behavior.

### `build_step2.py`

The prompt template and candidate checks are unchanged.
The caller can now set the model, reasoning effort, retry count, worker count, candidate counts, selected agents, selected instances, and output paths.

The model is now created only when it is needed.
The code keeps a model for reuse when the same model settings are used again.

The old code had more direct reuse of existing step output.
The current code processes the selected run and writes to the requested output paths.
This can change restart and result reuse behavior.

The package version can also receive an audit directory from the wrapper.
It writes the complete prompt before inference.
It writes each exact raw response before Pydantic parsing.
It records file sizes and SHA-256 checksums in an audit manifest.
It can reuse a compatible valid response from an earlier stage attempt.
This storage does not change the prompt template, candidate counts, or parsed expression values.

### `infer_expression.py`

The prompt construction and expression validation are unchanged.
Model creation changed from immediate creation during import to creation when inference starts.
The environment file, retry count, model, and reasoning effort can now be set by the caller.
The model call can receive a response-storage callback.
The callback completes before response parsing.

### `build_step3.py`

The expression execution and validation functions are retained.
The caller must select either the execute operation or the validate operation.

The caller can now set the prediction file, run identifier, log directory, work directory, report directory, SWE-bench settings, worker count, selected agents, and selected instances.
The current code also has controls for processing gold results and for handling existing gold output.
These changes affect run control, output reuse, and error checks.

### `build_step4.py`

The choice selection method and the maximal marginal relevance calculation are unchanged.
The caller can now set the number of choices, minimum pool sizes, selection weight, random seed, worker count, selected agents, selected instances, and output paths.

The defaults match the old fixed values.
Changing these options can change the generated answer choices.

### `build_step5.py`

The context and ground-truth export structure is unchanged when the default options are used.
The caller can now set the maximum parameter length, selected agents, selected instances, output paths, and output kind.
The output kind can select effect data, intent data, or both.

## Execution changes

The files under `execution` run tracking, tracing, and expression inspection through SWE-bench.

### `track.py` and `trace.py`

The tracer code that records calls and program state is unchanged.
The commands now accept explicit prediction files, whitelist files, run identifiers, timeouts, work directories, report directories, and SWE-bench settings.

Each command changes to the selected work directory before it starts SWE-bench.
It restores the previous work directory after the run.
This can change where tools find or create files.

### `inspect.py`

The expression inspection logic is unchanged.
The command now accepts explicit paths, run settings, and SWE-bench settings.
It creates the required work and report directories before the run.
It also changes to the selected work directory during the SWE-bench run.

### `monkey_patch/trace.py` and `monkey_patch/track.py`

The trace and track patches keep the same instrumentation logic.
They can now read a whitelist path from the run settings.
They use the included whitelist when the caller does not provide another path.

### `util.py`

The functions return the same SWE-bench test data after the dataset is loaded.
The current code loads the SWE-bench dataset when a function first needs it.
The old code loaded the dataset when the module was imported.

The package copy has one additional wheel support change.
It finds the installed `tracer` and `tracer_plugin` packages and builds the tracer archive for Docker.
The original repository used files from a separate `py-tracer` directory.
The paths inside the Docker environment remain the same.

### Files copied without changes

The following files match `main`:

- `allowed_functions.json`
- `allowed_qualnames.json`
- `monkey_patch/inspect.py`

## Evaluation changes

The package evaluation code lives under `src/explainbench/evaluation`.
The separate package does not install the historical top-level `evaluation` package.

Candidate generation imports `Model` and `InferencePersistenceError` directly from `explainbench.evaluation.inference`.
This direct import uses the same objects that the removed compatibility module re-exported.
It does not change candidate inference behavior.

Add new evaluation logic only under `src/explainbench/evaluation`.

## Tracer changes

The files under `tracer` and `tracer_plugin` match the tracer source used by the original repository.
No tracer calculation or serialization logic was changed during the package extraction.

The package change is in `execution/util.py`.
That file prepares the unchanged tracer source for the Docker environment.

## What a maintainer must check

Do not assume that a new command option changes only the command interface.
Check whether the option changes a calculation, a selected input, an output path, or restart behavior.

Use the default values when you compare results with `main`.
Use a small fixed set of instances for the comparison.
Compare the produced JSON files, trace files, and selected answer choices.

Pay special attention to these differences:

- Existing output reuse.
- Gold result reuse.
- Model creation and retries.
- Worker counts and timeouts.
- Random seeds and choice settings.
- Work and report directories.
- Custom whitelist files.
- Dataset loading time.

The current automated tests cover the package structure and several command paths.
They do not prove that every full Docker and model-backed run produces the same files as `main`.
