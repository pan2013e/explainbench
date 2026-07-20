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

The existing research pipeline under `dataset/extract_ground_truths/effect/` remains the behavioral reference. The package implementation will provide one canonical implementation of each operation. Existing research scripts may remain as thin compatibility wrappers, but the processing logic must not be maintained in two places.

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

Both interfaces call the same stage implementations. The `run` command resolves dependencies, invokes stages in order, and reports progress; it does not contain a second copy of the pipeline logic.

An individual stage command checks that its required upstream outputs are present and compatible. It reports the missing prerequisite and the command needed to produce it. It does not silently run earlier stages.

### Names describe what a stage does

CLI names, Python names, logs, and workspace directories should use the same plain-language terminology. Legacy names such as `build_step1` are recorded only as migration references.

| Order | Public stage name | Purpose | Current implementation reference |
|---:|---|---|---|
| 1 | `identify-patched-functions` | Find Python functions changed by the submitted patch in the before- and after-patch source. | `trace_step1_generate_qualname_whitelist.py` |
| 2 | `track-test-calls` | Run relevant tests with lightweight call tracking for the patched functions. | `execution.track` |
| 3 | `select-trace-functions` | Expand the patched-function set using the observed call paths and choose functions for detailed tracing. | `trace_step2_generate_call_stack_whitelist.py` |
| 4 | `trace-program-state` | Run the tests on buggy and patched code while recording detailed state for the selected functions. | `execution.trace` |
| 5 | `find-first-divergence` | Compare the two traces and locate the first useful state or control-flow difference. | `build_step1.py` |
| 6 | `generate-candidate-expressions` | Retrieve the relevant source and ask the configured model for expressions that may or may not change. | `build_step2.py` and `infer_expression.py` |
| 7 | `execute-candidate-expressions` | Evaluate every candidate at the divergence point in buggy and patched executions. | `build_step3.py --execute` |
| 8 | `validate-candidate-expressions` | Classify candidates from their recorded values as changed, unchanged, or unusable. | `build_step3.py --validate` |
| 9 | `build-answer-choices` | Select and shuffle one correct expression and suitable distractors, then add the special choices. | `build_step4.py` |
| 10 | `export-question-artifacts` | Write the context, ground truth, manifest, and failure report expected by the evaluator. | `build_step5.py` |

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
5. Execute missing, interrupted, or explicitly retried work.
6. Publish a complete evaluator artifact bundle.
7. Print counts for requested, completed, skipped, and failed instances.

The command returns a nonzero exit status if required infrastructure fails, a stage cannot complete, or no questions can be exported. Instance-level semantic skips do not by themselves make the entire run fail, but they are always reported.

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

Each runner operates on one submission instance where practical:

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

Stages that need an aggregate view, such as final export, may additionally implement a finalization operation after their instance results are durable.

## Workspace contract

The workspace is private builder state with a versioned, inspectable layout:

```text
.explainbench/builds/my-agent/
├── manifest.json
├── input/
│   └── submission.json
├── stages/
│   ├── identify-patched-functions/
│   │   ├── stage.json
│   │   └── instances/
│   │       └── astropy__astropy-12907/
│   │           ├── status.json
│   │           └── result.json
│   ├── track-test-calls/
│   │   └── ...
│   └── export-question-artifacts/
│       └── ...
├── logs/
│   └── STAGE/INSTANCE_ID/...
└── workspace.lock
```

Large native tracer outputs may live below the relevant instance directory instead of being copied into JSON. Their paths and checksums are recorded in that instance's result.

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
- `failed`: the attempt ended with a retryable or terminal error.
- `stale`: the result exists but its semantic fingerprint no longer matches.

`completed` and `skipped` statuses include the input fingerprint and point to a validated result. `failed` includes a structured failure category, message, attempt count, and log location.

### Durable writes

- Results are written to a temporary file, flushed, and atomically renamed.
- `completed` is written only after the result has passed that stage's schema validation.
- Stage summaries are derived from instance statuses and may be rebuilt; they are not the only checkpoint.
- Model responses are saved immediately per instance so paid inference is not lost.
- Docker logs and expression-inspection outputs are retained per instance.
- A final artifact directory is assembled in a temporary sibling directory and atomically published only after validation.

### Resume rules

With `--resume`:

- Compatible `completed` and `skipped` units are not rerun.
- A previous `running` unit is treated as interrupted and rerun safely.
- Retryable failures are retried according to the configured attempt limit.
- Terminal semantic skips remain skipped unless their semantic inputs change.
- Missing or corrupt result files make the unit stale even if `status.json` says `completed`.
- A stage is complete only when every requested instance has a durable terminal status and its aggregate output has been validated.

Without `--resume`, an existing nonempty workspace causes a clear error. Replacing work must require an explicit future `--restart` or `--force-stage` option; the first implementation must never silently delete expensive state.

### Compatibility fingerprints

Each instance-stage fingerprint includes only inputs that can change that stage's meaning:

- Instance ID and exact patch checksum.
- Stage name and implementation version.
- Relevant stage configuration.
- Checksums of required upstream results.
- Versions/checksums of bundled gold reference data used by the stage.
- Relevant external tool or tracer version.
- Model and semantic sampling settings for model-backed stages.

Operational settings such as worker count, retry count, and progress display do not invalidate semantic results. Changing a semantic input marks that stage and its downstream dependents stale for the affected instance; unrelated instances and upstream stages remain reusable.

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

## Package structure

Use explicit modules rather than one large pipeline file:

```text
src/explainbench/question_builders/
├── __init__.py
├── common/
│   ├── atomic_files.py
│   ├── fingerprints.py
│   ├── locking.py
│   ├── orchestration.py
│   └── status.py
└── local/
    ├── __init__.py
    ├── config.py
    ├── registry.py
    ├── workspace.py
    └── stages/
        ├── identify_patched_functions.py
        ├── track_test_calls.py
        ├── select_trace_functions.py
        ├── trace_program_state.py
        ├── find_first_divergence.py
        ├── generate_candidate_expressions.py
        ├── execute_candidate_expressions.py
        ├── validate_candidate_expressions.py
        ├── build_answer_choices.py
        └── export_question_artifacts.py
```

The `common` layer contains only genuinely reusable orchestration mechanisms. Local-effect concepts remain under `local`; a future end-to-end builder may define its own stage registry and stage implementations.

## Migration from the research pipeline

The migration creates one source of truth:

1. Extract a small piece of legacy logic into the corresponding package stage.
2. Add unit or fixture-based equivalence tests for its inputs and outputs.
3. Change the legacy script into a thin argument-translation wrapper over the package API, if the script still needs to be supported.
4. Remove unused hard-coded agent lists, global output paths, and duplicated processing logic from that wrapper.

Important corrections made during migration:

- Process one submitted model independently; do not intersect valid instances across historical agents.
- Replace shared global `allowed_qualnames.json` and `allowed_functions.json` with per-instance stage results.
- Replace UID-derived log locations with workspace-owned paths.
- Require the explicit execute or validate operation currently missing from the legacy `build_step3.py` README command.
- Define answer-choice selection configuration inside the package instead of relying on a module global initialized only by `__main__`.
- Avoid mutating upstream metadata while building choices.
- Defer dataset loading until it is needed instead of performing it at module import time.

## Implementation sequence

### Milestone 1: Orchestration foundation

- [x] Add the stage registry and dependency resolver.
- [x] Add versioned workspace and status schemas.
- [x] Add semantic fingerprints, atomic writes, and workspace locking.
- [x] Add the `run`, `stage`, `stages`, and `status` CLI shapes.
- [x] Exercise the runner with small fake stages; do not require Docker or a model API.
- [x] Test interruption, corrupt checkpoints, partial completion, retry, stale downstream work, and concurrent writer rejection.

Expected outcome: the CLI and resume machinery are real and thoroughly testable, while stage bodies may still report that the legacy operation has not yet been migrated.

Status: completed. The production registry currently uses explicit `stage_not_migrated` runners, so it cannot accidentally emit dummy scientific artifacts. The orchestration tests use injected lightweight runners and cover compatible reuse, per-instance interruption, retryable failure, corrupted results, semantic invalidation, operational-setting changes, missing prerequisites, dependency cycles, and workspace locking. The full fast test suite passes.

### Milestone 2: Pure transformation stages

- [x] Migrate `identify-patched-functions`.
- [x] Migrate `select-trace-functions` using stored tracking fixtures.
- [x] Migrate `find-first-divergence` using stored trace fixtures.
- [x] Migrate `validate-candidate-expressions`.
- [x] Migrate `build-answer-choices`.
- [x] Migrate and validate `export-question-artifacts`.
- [x] Turn the corresponding legacy scripts into wrappers as each migration completes.

Expected outcome: deterministic and non-service-backed processing can be run and resumed through the package, and fixture inputs can produce evaluator-compatible artifacts.

Status: completed. The stage contracts now make tracked-call files, detailed trace pairs, expression-inspection payloads, validated pools, and final question records explicit. Missing or corrupt traces are failures and cannot silently activate gold fallback. Gold fallback is emitted only after at least one valid trace pair has been exhaustively compared without finding a usable agent divergence. Choice randomization uses a stable per-instance seed so checkpoint reuse and worker scheduling cannot change a question. Export is tested by loading the generated artifact bundle through the evaluator's typed `local.effect` artifact loader.

### Milestone 3: Docker execution stages

- Migrate `track-test-calls`.
- Migrate `trace-program-state`.
- Migrate `execute-candidate-expressions`.
- Parameterize repository cache, image, timeout, worker, and log locations.
- Keep Docker containers and subprocesses scoped to one instance attempt.
- Add an opt-in slow integration test for one small SWE-bench instance.

Expected outcome: execution evidence is generated directly in the versioned workspace and can resume at instance granularity after interruption.

### Milestone 4: Model-backed candidate generation

- Migrate source retrieval and `generate-candidate-expressions`.
- Move model, reasoning, sampling, retry, and concurrency settings into typed builder configuration.
- Persist each raw response before parsing and persist each validated result immediately.
- Distinguish API/transient failures from semantic inability to produce valid candidates.

Expected outcome: paid model work is durable and independently retryable, completing the functional local-effect pipeline.

### Milestone 5: Compatibility, packaging, and documentation

- Complete any remaining legacy wrappers and remove duplicated logic.
- Verify the required runtime resources are included in the wheel.
- Test a clean wheel installation outside the repository.
- Document disk, Docker, network/model, and expected runtime requirements.
- Run a small end-to-end build followed by `explainbench evaluate --task local.effect`.

Expected outcome: an installed ExplainBench package can construct and evaluate local-effect questions without relying on repository-relative commands or hard-coded historical agents.

## Testing strategy

- Unit tests for schemas, fingerprints, dependency resolution, and status transitions.
- Golden tests comparing migrated pure stages with known legacy outputs.
- CLI tests for valid commands, missing prerequisites, invalid stage names, and status output.
- Failure-injection tests that interrupt after selected instances and confirm `--resume` reruns only incomplete units.
- Tests proving semantic config changes invalidate the correct stage and downstream stages only.
- Tests proving worker/retry changes preserve completed semantic results.
- Tests distinguishing gold fallback from infrastructure failure.
- Atomic-publication tests ensuring the evaluator never observes a half-written artifact bundle.
- Optional Docker and model-backed integration tests, excluded from the default fast suite.

## Out of scope for the first local implementation

- Automatic installation or validation of Docker and system dependencies.
- Automatic local question building inside `explainbench evaluate`.
- End-to-end effect question construction.
- Automatic deletion of large traces or Docker artifacts.
- Redesigning the scientific question-generation method while migrating it.

## Current status

- [x] Inspect and map the existing local-effect research pipeline.
- [x] Agree to preserve the current gold fallback behavior.
- [x] Agree on separate per-stage and complete-run commands.
- [x] Agree on instance-level checkpointing and semantic resume validation.
- [x] Define meaningful public stage names and map them to legacy operations.
- [x] Detail the workspace, command, artifact, and migration contracts.
- [x] Implement Milestone 1: orchestration foundation.
- [x] Implement Milestone 2: pure transformation stages.
- [ ] Implement Milestone 3: Docker execution stages.
- [ ] Implement Milestone 4: model-backed candidate generation.
- [ ] Implement Milestone 5: compatibility, packaging, and documentation.

## Next step

Implement Milestone 3 next, beginning with `track-test-calls`. Each Docker stage should emit the explicit per-instance file contract already consumed by its downstream deterministic stage, retain its container logs in the workspace, and use the existing retry/checkpoint boundary rather than introducing another resume mechanism.
