# Local-Effect Question Builder Implementation Plan

## Purpose

This document records the agreed design and implementation status for:

```bash
explainbench question-builder local ...
```

The local-effect builder runs a submitted patch, records its execution behavior, and converts the observed behavior into the model-specific question artifacts consumed by:

```bash
explainbench evaluate submission.json --task local.effect ...
```

The existing pipeline under `dataset/extract_ground_truths/effect/` and `execution/` is the canonical implementation. Its scientific logic must remain there. The package layer under `src/explainbench` only prepares submission-specific inputs, invokes the canonical command-line entry points, validates their declared outputs, and records orchestration checkpoints.

The ownership direction is therefore:

```text
explainbench CLI/orchestrator
  -> canonical dataset/execution CLI
  -> existing pipeline functions
```

It must never point in the opposite direction. In particular, modules under `dataset/` and `execution/` must not import question-builder stage implementations from `src/explainbench`, and scientific functions must not be copied into `src/explainbench`.

The initial scope is local effect. The orchestration and workspace abstractions should be reusable by a future end-to-end effect builder without forcing its stages to be identical to the local pipeline.

## Design decisions

### Both individual stages and a complete run are supported

Every stage can be invoked separately for development, debugging, and recovery:

```bash
explainbench question-builder local stage identify-patched-functions \
  submission.json \
  --workspace .explainbench/builds/my-agent
```

The complete pipeline can also be orchestrated with one command:

```bash
explainbench question-builder local run submission.json \
  --workspace .explainbench/builds/my-agent \
  --output question-artifacts \
  --resume
```

Both interfaces resolve to the same canonical legacy CLI commands. The `run` command resolves dependencies, invokes those commands in order, and reports progress; it does not contain a second copy of the pipeline logic.

An individual stage command checks that its required upstream outputs are present and compatible. It reports the missing prerequisite and the command needed to produce it. It does not silently run earlier stages.

### Names describe what a stage does

CLI names, Python names, logs, and workspace directories should use the same plain-language terminology. Legacy names such as `build_step1` are recorded only as migration references.

| Order | Public stage name | Purpose | Canonical CLI module |
|---:|---|---|---|
| 1 | `identify-patched-functions` | Find Python functions changed by the submitted patch in the before- and after-patch source. | `python -m dataset.extract_ground_truths.effect.trace_step1_generate_qualname_whitelist` |
| 2 | `track-test-calls` | Run relevant tests with lightweight call tracking for the patched functions. | `python -m execution.track` |
| 3 | `select-trace-functions` | Expand the patched-function set using the observed call paths and choose functions for detailed tracing. | `python -m dataset.extract_ground_truths.effect.trace_step2_generate_call_stack_whitelist` |
| 4 | `trace-program-state` | Run the tests on buggy and patched code while recording detailed state for the selected functions. | `python -m execution.trace` |
| 5 | `find-first-divergence` | Compare the two traces and locate the first useful state or control-flow difference. | `python -m dataset.extract_ground_truths.effect.build_step1` |
| 6 | `generate-candidate-expressions` | Retrieve the relevant source and ask the configured model for expressions that may or may not change. | `python -m dataset.extract_ground_truths.effect.build_step2` |
| 7 | `execute-candidate-expressions` | Evaluate every candidate at the divergence point in buggy and patched executions. | `python -m dataset.extract_ground_truths.effect.build_step3 --execute` |
| 8 | `validate-candidate-expressions` | Classify candidates from their recorded values as changed, unchanged, or unusable. | `python -m dataset.extract_ground_truths.effect.build_step3 --validate` |
| 9 | `build-answer-choices` | Select and shuffle one correct expression and suitable distractors, then add the special choices. | `python -m dataset.extract_ground_truths.effect.build_step4` |
| 10 | `export-question-artifacts` | Write the context and ground truth expected by the evaluator. | `python -m dataset.extract_ground_truths.effect.build_step5` |

The canonical CLIs receive explicit agent/submission ID, instance IDs, input paths, output paths, worker limits, and stage-specific settings. Defaults may preserve the research reproduction workflow, but package wrappers always pass explicit paths and never depend on hard-coded historical agents.

The command will list these names in order:

```bash
explainbench question-builder local stages
```

### Work state and deliverable artifacts are separate

`--workspace` contains checkpoints, traces, Docker logs, model responses, and other resumable state. It may be large and is not passed to the evaluator.

`--output` contains the small, stable artifact bundle passed to `explainbench evaluate`. Publishing it is the responsibility of `export-question-artifacts`.

This distinction makes cleanup safe: final question artifacts can be retained while large traces are removed explicitly later.

## Command contract

### Run the complete pipeline

```bash
explainbench question-builder local run SUBMISSION \
  --workspace WORKSPACE \
  --output ARTIFACT_DIRECTORY \
  [--config CONFIG] \
  [--resume]
```

Expected behavior:

1. Validate that every selected submission instance has a nonempty patch.
2. Create or validate the workspace manifest.
3. Resolve the local-stage dependency graph.
4. Skip compatible completed instance work when `--resume` is used.
5. Execute missing or interrupted work.
6. Give every retryable failure a fresh retry cycle for each new `--resume` invocation.
7. Publish a complete evaluator artifact bundle.
8. Print counts for requested, completed, skipped, and failed instances.

The command returns a nonzero exit status if required infrastructure fails, a stage cannot complete, or no questions can be exported.
Instance-level semantic skips do not by themselves make the entire run fail, but they are always reported.

### Run one stage

```bash
explainbench question-builder local stage STAGE SUBMISSION \
  --workspace WORKSPACE \
  [--output ARTIFACT_DIRECTORY] \
  [--config CONFIG] \
  [--resume]
```

`--output` is required only for `export-question-artifacts`. The stage command uses the same configuration parsing, fingerprints, locks, checkpoints, and status reporting as the complete runner.

### Inspect a workspace

The first implementation should also provide a read-only status command:

```bash
explainbench question-builder local status \
  --workspace .explainbench/builds/my-agent
```

It should show:

- Submission ID and submission fingerprint.
- Stage completion counts.
- Currently running or previously interrupted work.
- Failed instances and concise failure reasons.
- Retry cycle, current cycle attempt, and cumulative attempt count for incomplete work.
- Stale stages that need recomputation.
- Whether final artifacts have been exported.

## Stage dependency graph

The local pipeline is initially linear:

```text
identify-patched-functions
  -> track-test-calls
  -> select-trace-functions
  -> trace-program-state
  -> find-first-divergence
  -> generate-candidate-expressions
  -> execute-candidate-expressions
  -> validate-candidate-expressions
  -> build-answer-choices
  -> export-question-artifacts
```

Dependencies are declared as data in a stage registry. They must not be duplicated as a long sequence of calls inside the CLI. This leaves room to add a branch, reuse a stage, or define a different end-to-end pipeline later.

Conceptually:

```python
@dataclass(frozen=True)
class StageDefinition:
    name: str
    dependencies: tuple[str, ...]
    implementation_version: str
    runner: StageRunner
```

Each package runner operates on one submission instance where practical by invoking the corresponding canonical CLI with that instance ID:

```python
class StageRunner(Protocol):
    def run_instance(
        self,
        instance: SubmissionInstance,
        workspace: LocalBuilderWorkspace,
        config: LocalBuilderConfig,
    ) -> StageResult:
        ...
```

The runner implementation contains command construction and output validation only. Parsing traces, identifying divergences, generating candidates, validating expressions, and assembling questions remain functions of the canonical modules.

Stages that need an aggregate view, such as final export, may additionally implement a finalization operation after their instance results are durable.

## Workspace contract

The workspace is private builder state with a versioned, inspectable layout:

```text
.explainbench/builds/my-agent/
├── manifest.json
├── input/
│   ├── submission.json
│   └── predictions.json
├── stages/
│   ├── identify-patched-functions/
│   │   ├── stage.json
│   │   └── instances/
│   │       └── astropy__astropy-12907/
│   │           ├── status.json
│   │           ├── result.json
│   │           └── work/
│   │               ├── attempt-1/
│   │               │   ├── attempt.json
│   │               │   ├── stdout.log
│   │               │   └── stderr.log
│   │               └── attempt-2/
│   ├── track-test-calls/
│   │   └── ...
│   └── export-question-artifacts/
│       └── ...
├── logs/
│   └── STAGE/INSTANCE_ID/...
└── workspace.lock
```

Large native tracer outputs may live below the relevant instance directory instead of being copied into JSON.
Their paths, sizes, and checksums are recorded in that instance's artifact manifest.
Each attempt writes to its own directory, so a partial output from an interrupted attempt cannot replace a completed result.

`manifest.json` records:

- Workspace schema version.
- ExplainBench version.
- Submission ID and deterministic submission fingerprint.
- Selected instance IDs.
- Configuration fingerprint for each stage.
- Stage implementation versions.
- Creation and update timestamps.
- Stage-level completion summaries.
- Final export location and artifact fingerprint, when available.

The normalized submission is copied to `input/submission.json`. This is an auditable snapshot, not a second source of truth: its checksum must match the manifest before resuming.

## Robust checkpoint and resume behavior

### Checkpoint unit

The checkpoint unit is one stage and one benchmark instance. A six-hour stage must not lose all completed work because a later instance fails.

Every unit has a `status.json` with one of:

- `pending`: no attempt has started.
- `running`: an attempt started but has not produced a durable result.
- `completed`: a validated result was written successfully.
- `skipped`: processing completed with an intentional semantic reason.
- `failed`: the attempt ended with a retryable or non-retryable error.
- `stale`: the saved result or artifact is no longer compatible or trustworthy.

`completed` and `skipped` statuses include the semantic input fingerprint and point to a validated result.
`failed` includes a structured failure category, message, retryability, retry-cycle counters, and log location.

Each status records these attempt counters:

- `retry_cycle`: the command invocation that performed the attempts.
- `cycle_attempt`: the attempt number inside the current command invocation.
- `total_attempts`: the cumulative number of attempts retained for audit and debugging.

`cycle_attempt` starts from zero when a new `--resume` command begins and becomes one when the first new attempt starts.
`total_attempts` never resets.
The attempt directory number uses `total_attempts`, so attempt history is never overwritten when a cycle resets.

Adding these fields requires instance checkpoint status schema version 2.
The workspace loader will upgrade version 1 development checkpoints under the workspace lock.
It will map the old `attempts` value to `total_attempts`, preserve the old fingerprint as the semantic fingerprint, and start the next eligible resume as a new retry cycle.

### Durable writes

- Results are written to a temporary file, flushed, and atomically renamed.
- `completed` is written only after the result has passed that stage's schema validation.
- Every subprocess attempt writes to `work/attempt-N/` and has separate stdout and stderr logs.
- A wrapper publishes `result.json` only after the canonical command exits successfully and all declared outputs pass validation.
- Stage summaries are derived from instance statuses and may be rebuilt; they are not the only checkpoint.
- Model responses are saved immediately per instance so paid inference is not lost.
- Docker logs and expression-inspection outputs are retained per instance.
- Large outputs use an artifact manifest that records every downstream input file and its checksum.
- A final artifact directory is assembled in a temporary sibling directory and atomically published only after validation.

### Resume rules

With `--resume`:

- Compatible `completed` and `skipped` units are not rerun.
- A previous `running` unit is treated as interrupted after the new process acquires the workspace lock.
- The interrupted unit starts a new retry cycle and writes to a new attempt directory.
- A retryable failure receives a fresh retry cycle with up to `max_attempts` attempts on every new `--resume` invocation.
- No separate `--retry-failed` option is required.
- A non-retryable failure remains failed until its patch, semantic configuration, upstream result, or stage implementation changes.
- Terminal semantic skips remain skipped unless their semantic inputs change.
- Missing or corrupt result files make the unit stale even if `status.json` says `completed`.
- Missing, modified, or corrupt external artifacts also make the unit stale.
- When a unit becomes stale, that unit and its downstream dependents become stale for the affected instance only.
- A stage is complete only when every requested instance has a durable terminal status and its aggregate output has been validated.

Without `--resume`, an existing nonempty workspace causes a clear error.
Replacing work must require an explicit future `--restart` or `--force-stage` option.
The first implementation must never silently delete expensive state.

### Retry-cycle policy

`max_attempts` limits one command invocation, not the complete lifetime of the workspace.
For example, `max_attempts = 3` permits three attempts during the initial run.
If all three attempts have retryable failures, the command stops and preserves the failure.
A later `--resume` command automatically starts a new cycle with another budget of three attempts.

This policy keeps every command invocation bounded while making manual recovery simple.
The user does not need an additional retry option.
Repeated retries require repeated user invocations, so the system cannot enter an unlimited automatic loop.

The resume behavior by state is:

| Previous state | Action during `--resume` |
|---|---|
| Compatible `completed` or `skipped` | Reuse the durable result. |
| `running` with no active workspace writer | Record an interruption and start a new retry cycle. |
| Retryable `failed` | Start a new retry cycle with `cycle_attempt = 0`. |
| Non-retryable `failed` | Preserve and report the failure. |
| Missing or corrupt result or artifact | Mark the stage and downstream stages stale, then rerun them. |
| Changed patch or semantic setting | Mark the affected stage and downstream stages stale for that instance. |
| Changed worker or concurrency setting | Reuse compatible completed results and apply the new setting only to new work. |

### Compatibility fingerprints

Each instance-stage completed-result fingerprint includes only inputs that can change that stage's meaning:

- Instance ID and exact patch checksum.
- Stage name and implementation version.
- Relevant stage configuration.
- Checksums of required upstream results.
- Versions/checksums of bundled gold reference data used by the stage.
- Relevant external tool or tracer version.
- Model and semantic sampling settings for model-backed stages.

Operational settings such as worker count, retry count, and progress display do not invalidate semantic results. Changing a semantic input marks that stage and its downstream dependents stale for the affected instance; unrelated instances and upstream stages remain reusable.

Attempt execution also has a separate execution fingerprint.
It contains settings such as timeout, retry policy, and other controls that can affect whether an incomplete attempt can finish.
Changing the execution fingerprint can make a failed or interrupted unit eligible for a new attempt, but it does not invalidate a compatible completed result.

### Concurrency safety

- The workspace has a process lock.
- A second writer receives a clear error naming the active workspace.
- The read-only `status` command may inspect a locked workspace.
- Worker processes write only inside their assigned instance-stage directory.
- Parent aggregation occurs after workers finish and validates every collected result.

## Result categories and gold fallback

The existing gold fallback is preserved, but it must not hide infrastructure problems.

### Semantic no-divergence

If the submitted patch executes successfully but no usable agent-specific divergence can be constructed, the pipeline may use the existing bundled, validated gold metadata. The instance is marked explicitly with:

```json
{
  "outcome": "completed_with_gold_fallback",
  "fallback_reason": "no_usable_agent_divergence"
}
```

The later question-building behavior remains compatible with the research pipeline: generated expressions are treated as incorrect and the special no-effect choice becomes the expected answer.

### Infrastructure or data failure

Docker startup errors, test timeouts, corrupt/missing traces, repository checkout problems, and model API failures are `failed`, not gold fallback. They retain logs and may be resumed or retried. This distinction prevents an operational problem from changing the benchmark label.

## Final evaluator artifact contract

Successful export produces the already-agreed submission-specific files:

```text
question-artifacts/
├── manifest.json
├── context/
│   └── local_effect__my-agent.json
├── ground_truths/
│   └── local_effect__my-agent.json
└── failures.json
```

The evaluator continues to depend only on this contract. It does not inspect builder checkpoints or care whether artifacts were generated by the packaged builder or staged manually.

The export manifest includes:

- Artifact schema version.
- Submission ID and patch fingerprint.
- Builder target (`local`).
- Included, skipped, fallback, and failed instance IDs.
- Relevant semantic configuration and model identifiers.
- Checksums of the context and ground-truth files.
- ExplainBench and builder implementation versions.

Export validates that context and ground-truth instance sets match and that every question satisfies the evaluator's typed local-effect schema.

Instance workers do not write the shared context and ground-truth files directly.
Each instance first produces a durable context and answer record in its checkpoint.
After instance processing finishes, one deterministic finalizer merges the compatible records and atomically publishes the shared files.
The finalizer can run again from existing checkpoints without repeating Docker execution or model inference.

## Package structure

Use explicit wrapper modules rather than duplicating the pipeline:

```text
src/explainbench/question_builders/
├── __init__.py
├── common/
│   ├── atomic_files.py
│   ├── fingerprints.py
│   ├── locking.py
│   ├── orchestration.py
│   ├── subprocess_runner.py
│   └── status.py
└── local/
    ├── __init__.py
    ├── config.py
    ├── registry.py
    ├── runners.py
    ├── workspace.py
    └── submission_adapter.py
```

The `common` layer contains only genuinely reusable orchestration mechanisms.
`subprocess_runner.py` runs canonical commands with isolated process groups, durable command records, and per-attempt logs.
`runners.py` declares each canonical module, its arguments, and its output validation.
It contains no scientific transformations.
A future end-to-end builder may define its own command registry and wrappers.

## Canonical CLI modernization

The work creates one source of scientific truth without moving it:

1. Preserve each existing processing function in `dataset/` or `execution/`.
2. Give its module a parameterized `main(argv=None)` CLI that accepts one submission and explicit workspace paths.
3. Keep historical defaults only for direct reproduction use; package calls pass every important value explicitly.
4. Add package runners that call `python -m <canonical-module> ...` and validate its output file.
5. Test command construction separately from scientific behavior, and retain existing scientific regression tests beside the canonical modules.

CLI-only corrections required for package use:

- Allow one submitted model to be processed independently instead of requiring a hard-coded agent list.
- Accept a submission-specific predictions JSON path instead of requiring `dataset/explanations/agent_patches/{agent}.json`.
- Accept explicit whitelist, trace-log, intermediate-output, and final-artifact paths.
- Accept explicit run IDs instead of deriving all state from the process UID.
- Accept explicit instance IDs and worker limits at every expensive stage.
- Make `build_step3` require exactly one of `--execute` or `--validate`.
- Make `build_step4` operate on the selected submission without intersecting historical agents.
- Preserve gold fallback behavior in the existing pipeline functions; wrappers only transport its outputs.

## Implementation sequence

### Milestone 1: Orchestration foundation

- [x] Add the stage registry and dependency resolver.
- [x] Add versioned workspace and status schemas.
- [x] Add semantic fingerprints, atomic writes, and workspace locking.
- [x] Add the `run`, `stage`, `stages`, and `status` CLI shapes.
- [x] Exercise the runner with small fake stages; do not require Docker or a model API.
- [x] Test interruption, corrupt checkpoints, partial completion, retry, stale downstream work, and concurrent writer rejection.

Expected outcome: the CLI and resume machinery are real and thoroughly testable, while stage bodies may still report that their canonical command has not yet been connected.

Status: completed.
Unconnected production stages use an explicit `stage_not_connected` runner, so they cannot emit dummy scientific artifacts.
The orchestration tests use injected lightweight runners and cover compatible reuse, per-instance interruption, retryable failure, corrupted results, semantic invalidation, operational-setting changes, missing prerequisites, dependency cycles, and workspace locking.
The full fast test suite passes.

### Milestone 2: Canonical command interfaces and package wrappers

- [x] Add explicit CLIs to both whitelist-generation scripts.
- [x] Parameterize the existing `execution.track` and `execution.trace` CLIs for predictions, whitelist, run ID, instances, and workers.
- [x] Add explicit CLIs to `build_step1.py` through `build_step5.py`, including separate step-3 execute and validate invocations.
- [x] Add instance checkpoint status schema version 2 with `retry_cycle`, `cycle_attempt`, `total_attempts`, and a separate execution fingerprint.
- [x] Add an atomic version 1 to version 2 workspace migration under the workspace lock.
- [x] Reset the retryable-failure budget for every new `--resume` invocation while retaining cumulative attempt history.
- [x] Convert abandoned `running` states into explicit interrupted attempts after the workspace lock is acquired.
- [x] Add isolated attempt directories and durable per-attempt records.
- [x] Add a shared checksummed external-artifact manifest for stage outputs that remain outside `result.json`.
- [x] Add a submission adapter that writes the canonical predictions shape inside the workspace.
- [x] Add the shared canonical subprocess runner with command records, stdout and stderr logs, timeout handling, and process-group cleanup.
- [x] Connect `identify-patched-functions` to its canonical CLI as the first real stage runner.
- [x] Connect `select-trace-functions` to the canonical call-stack whitelist CLI.
- Replace each remaining pending package runner with a thin subprocess wrapper over its canonical module.
- [x] Validate the `identify-patched-functions` output before marking its instance-stage checkpoint complete.
- [x] Validate the per-instance function whitelist produced by `select-trace-functions`.
- Add output validation for every remaining stage as each wrapper is connected.
- Add a single-writer finalizer that merges per-instance export records and publishes the evaluator artifacts atomically.
- [x] Test the canonical CLI parsing and dispatch without Docker or model calls.
- [x] Test the first wrapper's command construction without Docker or model calls.
- [x] Test the tracking and trace-function wrapper command construction without Docker or model calls.
- Test each remaining wrapper's command construction without Docker or model calls.
- [x] Test retry-budget reset across separate resume invocations.
- [x] Test that non-retryable failures do not restart without a compatible input or implementation change.
- [x] Test interruption recovery and attempt isolation.
- [x] Test that external-artifact corruption invalidates and reruns the owning stage.

Expected outcome: every existing local-question step can be invoked directly and through `explainbench question-builder local`, while scientific logic remains canonical under `dataset/` and `execution/`.

#### CLI hard-code audit

The canonical command-interface phase exposes the following values:

| Area | Exposed options |
|---|---|
| Submission selection | `--agent`, `--agents`, `--instance-ids`, `--predictions-path`, `--predictions-dir` |
| Workspace paths | repository cache, whitelist inputs/outputs, tracking root, trace root, inspection root/run ID, every step input/output, context directory, and ground-truth directory |
| SWE-bench harness | dataset name, split, run ID, timeout, workers, rebuild/clean behavior, cache level, file limit, namespace, image tags, and report directory |
| Divergence | depth threshold, default timeout, agent/instance workers, simplification toggle, variable depth, and parameter depth |
| Candidate generation | changed/unchanged candidate counts, inference toggle, model, reasoning effort, dotenv path, retries, and workers |
| Expression inspection | execute versus validate, gold-processing toggle, expression-set ID, inspection run ID, log root, predictions, and workers |
| Choice building | selected agents/instances, correct/incorrect counts, minimum pools, MMR weight, random seed, intent/effect mode, and workers |
| Export | intent/effect selection, selected agents/instances, step-4 inputs, output directories, and parameter truncation limit |

The following values intentionally remain canonical defaults rather than general CLI knobs for now:

- The benchmark-specific exclusion list and Django FAIL_TO_PASS corrections in `execution.util`.
- Per-instance exceptional divergence timeouts and alternate starting test IDs in `build_step1.py`.
- Randomized/wrapper function exception lists used by divergence detection.
- The tracer's in-container installation path and project-specific injected test-command rewrites.
- SWE-bench Docker platform/image naming and the source-extraction joblib cache implementation.
- The scientific prompt template and special answer text.

These values affect benchmark compatibility or internal implementation rather than ordinary submission/workspace selection. They can be revisited individually if a concrete use case requires an override.

Status of the CLI-only phase: completed.
Import-time SWE-bench dataset loading was also made lazy, so `--help` and argument validation do not require network or dataset-cache access.
The generic resume foundation, revised retry-cycle behavior, submission adapter, shared subprocess runner, and first three canonical stage integrations are implemented.
The shared artifact manifest records relative paths, sizes, and SHA-256 checksums.
Resume validates the full recorded file set before it reuses a checkpoint.
The remaining canonical stage wrappers are not yet implemented.

### Milestone 3: Docker execution stages

- [x] Connect `track-test-calls` to the canonical `execution.track` command.
- Connect the remaining Docker package runners to the canonical `execution.trace` and `execution.inspect` commands.
- [x] Pass tracking timeouts, worker count, whitelist, prediction, run-ID, report, and log locations explicitly.
- Pass the corresponding values explicitly for tracing and inspection.
- Keep Docker containers and subprocesses scoped to one instance attempt.
- Add an opt-in slow integration test for one small SWE-bench instance.

Expected outcome: the existing canonical execution code writes evidence into the versioned workspace through thin package wrappers and can later resume at instance granularity after interruption.

### Milestone 4: Model-backed candidate generation

- Connect source retrieval and candidate generation to the canonical `build_step2.py` command.
- Pass model, reasoning, sampling, retry, and concurrency settings from typed builder configuration to that command.
- Persist each raw response before parsing and persist each validated result immediately.
- Distinguish API/transient failures from semantic inability to produce valid candidates.

Expected outcome: paid model work is durable and independently retryable, completing the functional local-effect pipeline.

### Milestone 5: Compatibility, packaging, and documentation

- Complete the remaining thin wrappers and verify that scientific logic is not duplicated in `src/`.
- Verify the required runtime resources are included in the wheel.
- Test a clean wheel installation outside the repository.
- Document disk, Docker, network/model, and expected runtime requirements.
- Run a small end-to-end build followed by `explainbench evaluate --task local.effect`.

Expected outcome: an installed ExplainBench package can construct and evaluate local-effect questions without relying on repository-relative commands or hard-coded historical agents.

## Testing strategy

- Unit tests for schemas, fingerprints, dependency resolution, and status transitions.
- Golden tests comparing parameterized canonical stages with known historical outputs.
- CLI tests for valid commands, missing prerequisites, invalid stage names, and status output.
- Failure-injection tests that interrupt after selected instances and confirm `--resume` reruns only incomplete units.
- Tests proving that each new resume invocation resets `cycle_attempt` while preserving `total_attempts`.
- Tests proving that an exhausted retryable failure receives a new attempt budget on the next resume invocation.
- Tests proving that a non-retryable failure remains blocked across resume invocations.
- Tests proving semantic config changes invalidate the correct stage and downstream stages only.
- Tests proving worker/retry changes preserve completed semantic results.
- Tests proving timeout changes can affect new attempts without invalidating completed results.
- Tests proving missing or corrupt external trace artifacts invalidate the owning stage and downstream stages only.
- Tests distinguishing gold fallback from infrastructure failure.
- Atomic-publication tests ensuring the evaluator never observes a half-written artifact bundle.
- Optional Docker and model-backed integration tests, excluded from the default fast suite.

## Out of scope for the first local implementation

- Automatic installation or validation of Docker and system dependencies.
- Automatic local question building inside `explainbench evaluate`.
- End-to-end effect question construction.
- Automatic deletion of large traces or Docker artifacts.
- Redesigning the scientific question-generation method while exposing and wrapping it.

## Current status

- [x] Inspect and map the existing local-effect research pipeline.
- [x] Agree to preserve the current gold fallback behavior.
- [x] Agree on separate per-stage and complete-run commands.
- [x] Agree on instance-level checkpointing and semantic resume validation.
- [x] Define meaningful public stage names and map them to legacy operations.
- [x] Detail the workspace, command, artifact, and canonical-wrapper contracts.
- [x] Implement Milestone 1: orchestration foundation.
- [x] Implement the CLI-interface portion of Milestone 2.
- [x] Agree that each new resume invocation gives retryable failures a fresh retry budget by default.
- [x] Agree that no separate retry-failed CLI option is needed.
- [x] Implement instance status schema version 2, version 1 migration, per-invocation retry cycles, and durable attempt history.
- [x] Implement the submission adapter and shared canonical subprocess runner.
- [x] Connect and validate `identify-patched-functions` as the first real stage.
- [x] Connect `track-test-calls` to `execution.track` with attempt-scoped SWE-bench logs.
- [x] Add checksummed trace-artifact manifests and validate them during resume.
- [x] Separate the in-container test timeout from the complete tracking-command timeout.
- [x] Connect and validate `select-trace-functions` as the third canonical stage.
- [ ] Complete Milestone 2 with the submission adapter, thin package wrappers, and output validation.
- [ ] Implement Milestone 3: Docker execution stages.
- [ ] Implement Milestone 4: model-backed candidate generation.
- [ ] Implement Milestone 5: compatibility, packaging, and documentation.

## Next step

Connect `trace-program-state` to the canonical `execution.trace` command next.
The wrapper will consume the validated function whitelist from `select-trace-functions`.
It will run detailed buggy and patched state tracing in an attempt-scoped SWE-bench workspace.
It will record the detailed trace files in a checksummed artifact manifest for `find-first-divergence`.
Keep the real SWE-bench and Docker smoke test opt-in because the default suite must remain fast and offline.
