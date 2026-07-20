# ExplainBench Python Package Plan

## Goal

Turn ExplainBench from a repository-oriented replication package into an installable Python package:

```bash
pip install explainbench
```

Users will interact with it through one command:

```bash
explainbench checker ...
explainbench question-builder ...
explainbench evaluate ...
```

The initial evaluation implementation supports both local and end-to-end intent, plus model-specific effect evaluation when the corresponding effect artifacts are available. Initial question-builder development still focuses on local effect. The internal design must allow end-to-end question building to be added without redesigning the submission format, CLI, result format, or evaluation registry.

Environment diagnostics and automatic checking of Docker/system dependencies are intentionally out of scope for the initial implementation.

## Agreed submission format

ExplainBench will accept one JSON document per submission:

```json
{
  "submission_id": "my-agent",
  "instances": [
    {
      "instance_id": "astropy__astropy-12907",
      "model_patch": "diff --git a/astropy/modeling/separable.py b/astropy/modeling/separable.py\n...",
      "explanation": "The patch fixes the separability calculation by..."
    }
  ]
}
```

This combines the two formats currently used by the repository:

- Explanations are currently stored in `dataset/explanations/dataset.json` as `submission_id -> instance_id -> list[str]`.
- Patches are currently stored in one file per agent under `dataset/explanations/agent_patches/` using the fields `instance_id`, `model_patch`, and `model_name_or_path`.

The new format keeps the existing SWE-bench-compatible field names `instance_id` and `model_patch`, removes the unnecessary one-element explanation list, and moves the repeated agent/model name into the top-level `submission_id`.

### Initial validation rules

- The document must be valid JSON.
- `submission_id` is required and must be a nonempty string.
- `instances` is required and must be a nonempty list.
- Every instance must have a unique, nonempty `instance_id`.
- Every instance must contain a nonempty string `explanation`.
- `model_patch` is optional for intent-only evaluation.
- `model_patch` is required and must be nonempty for question building or any evaluation selection containing an effect task.
- Supported instance IDs must belong to the ExplainBench benchmark set.
- Unknown fields will initially be rejected so misspelled fields do not pass silently.
- Version 1 supports one explanation per instance.

The Python representation will be defined with Pydantic models. All commands will share the same parser and validation functions.

## Initial CLI contract

### Validate a submission

```bash
explainbench checker submission.json
```

The checker validates the file and benchmark IDs. It does not run patches or inspect Docker/system dependencies.

### Build local-effect questions

```bash
explainbench question-builder local submission.json \
  --output ./question-artifacts
```

Question building is an explicit operation. Full evaluation will not automatically invoke it.

### Run intent evaluation

```bash
explainbench evaluate submission.json \
  --mode lite \
  --output ./results.json
```

Lite mode evaluates:

- `e2e.intent`
- `local.intent`

It requires only the submitted explanations and the submission-independent intent questions bundled with ExplainBench.

### Run all intent and effect tasks

```bash
explainbench evaluate submission.json \
  --mode full \
  --artifacts-dir ./question-artifacts \
  --output ./results.json
```

Full mode evaluates:

- `e2e.intent`
- `e2e.effect`
- `local.intent`
- `local.effect`

Full evaluation must fail clearly if required model-specific effect artifacts are missing or incomplete.

### Run selected tasks

Fine-grained selection uses repeatable task options:

```bash
explainbench evaluate submission.json \
  --task local.intent \
  --task e2e.effect \
  --artifacts-dir ./question-artifacts \
  --output ./results.json
```

Supported task names are `e2e.intent`, `e2e.effect`, `local.intent`, and `local.effect`. `--mode` and `--task` are mutually exclusive.

See `EVALUATION_PLAN.md` for the detailed evaluation and artifact design.

## Proposed package structure

Use a `src`-based public package:

```text
src/explainbench/
├── __init__.py
├── cli.py
├── schemas.py
├── submission.py
├── checker.py
├── artifacts.py
├── evaluation/
│   ├── runner.py
│   ├── registry.py
│   └── tasks/
│       ├── local_intent.py
│       └── local_effect.py
└── question_builders/
    ├── base.py
    └── local.py
```

The command will be registered in `pyproject.toml`:

```toml
[project.scripts]
explainbench = "explainbench.cli:main"
```

Existing research modules can remain in place while stable APIs are introduced. The CLI must call Python functions rather than invoke the existing scripts through subprocesses.

Installed package resources must be treated as read-only. Logs, intermediate data, generated questions, predictions, and results must be written beneath a user-selected output directory.

## Implementation phases

### Phase 1: Submission schema and checker

Implement:

- Pydantic models for the agreed JSON format.
- A shared JSON loader and validator.
- Validation profiles for base/lite and question-builder/full requirements.
- Duplicate instance detection.
- Benchmark instance-ID validation.
- Basic unified-diff validation for nonempty patches.
- Human-readable errors with an appropriate nonzero exit status.
- `explainbench checker submission.json`.

Example successful output:

```text
Submission is valid
Submission ID: my-agent
Instances: 42
Explanations: 42
Patches: 40
```

### Phase 2: Installable CLI and lite evaluation

Implement the first complete user workflow:

```text
submission.json
  -> validate
  -> load bundled local-intent and end-to-end-intent questions
  -> ask the evaluator model using each explanation
  -> score predictions
  -> write results.json
```

Refactor the existing evaluator so it accepts explicit inputs rather than deriving everything from an agent ID:

- Submission object instead of `dataset.json[agent_id]`.
- Context and ground-truth objects instead of fixed repository-relative paths.
- Explicit output path instead of the current `results/` convention.
- Task names resolved through a registry.

The result document should include configuration, token usage, summary statistics, and per-instance results for each task.

### Phase 3: Versioned question-artifact bundle

Define the output contract shared by temporary manually staged effect artifacts and the future question builders:

```text
question-artifacts/
├── manifest.json
├── context/
│   ├── local_effect__{submission_id}.json
│   └── e2e_effect__{submission_id}.json
├── ground_truths/
│   ├── local_effect__{submission_id}.json
│   └── e2e_effect__{submission_id}.json
├── failures.json
├── intermediate/
│   ├── divergences.json
│   ├── expressions.json
│   └── validated_expressions.json
└── logs/
```

The manifest should record:

- Artifact schema version.
- ExplainBench package version.
- Builder type (`local`).
- Submission ID.
- A deterministic checksum of the instance IDs and patches.
- Included, skipped, and failed instance IDs.
- Completion state for each stage.
- Relevant models and builder configuration.

The checksum binds the generated questions to the exact submitted patches. Intermediate files make expensive question construction resumable and debuggable.

### Phase 4: Refactor the local-effect pipeline

Convert the current script sequence into parameterized Python functions. The existing process consists of:

1. Generate a qualified-name whitelist.
2. Run tracked executions.
3. Generate a call-stack whitelist.
4. Run traced executions.
5. Identify divergent execution state.
6. Infer candidate expressions.
7. Execute and validate candidate expressions.
8. Select question choices.
9. Export context and ground truth.

Replace hard-coded agent lists, paths, instance selections, worker counts, and output destinations with an explicit configuration object. For example:

```python
@dataclass
class LocalBuilderConfig:
    submission_path: Path
    output_dir: Path
    instance_ids: list[str]
    workers: int
    inference_model: str
```

The resulting API should conceptually be:

```python
def build_local_questions(config: LocalBuilderConfig) -> QuestionBundle:
    ...
```

Existing scripts may temporarily become compatibility wrappers around these functions.

### Phase 5: Remove multi-agent research assumptions

The current dataset-construction scripts process predefined agent lists and sometimes intersect usable instances across agents. The package must instead process one user submission independently:

- Retain an instance when that submission produces sufficient valid artifacts.
- Do not intersect its instances with historical agent submissions.
- Let one instance fail without aborting unrelated instances.
- Reuse bundled or precomputed submission-independent reference data.
- Generate only artifacts that depend on the submitted patch.
- Record explicit reasons for skipped and failed instances.

Question-builder output should summarize:

```text
Requested instances: 50
Questions generated: 43
Skipped: 5
Failed: 2
```

### Phase 6: Full and fine-grained evaluation

Connect shared intent resources and model-specific effect artifacts to the evaluator. Resolve modes through a registry:

```python
MODES = {
    "lite": ["e2e.intent", "local.intent"],
    "full": ["e2e.intent", "e2e.effect", "local.intent", "local.effect"],
}
```

Evaluation will:

1. Resolve either a mode preset or one or more explicit tasks.
2. Validate the submission according to the selected tasks.
3. Load packaged shared intent artifacts and selected model-specific effect artifacts.
4. Run generation and scoring for each selected task.
5. Report task-level, combined, skipped, and failed results.

### Phase 7: Packaging, testing, and documentation

Add:

- Unit tests for submission validation, checker errors, checksums, artifact manifests, and scoring.
- CLI tests for valid and invalid invocations.
- A small fixture for testing question-builder stage orchestration without Docker.
- An optional slow Docker integration test for a small number of SWE-bench instances.
- A wheel installation test in a clean virtual environment.
- User documentation for the checker, question builder, lite evaluation, and full evaluation.

The clean installation test must verify that commands work outside the repository root:

```bash
explainbench --help
explainbench checker submission.json
explainbench evaluate submission.json --mode lite --output results.json
```

## Extensibility for end-to-end evaluation

Question builders should implement a common interface:

```python
class QuestionBuilder(Protocol):
    target: str

    def build(
        self,
        submission: Submission,
        output_dir: Path,
    ) -> QuestionBundle:
        ...
```

Only the local implementation will be built initially. A future end-to-end implementation can register another builder and evaluation tasks without changing the submission schema or existing commands.

## Recommended next milestone

Proceed with Phase 2 and produce the first complete evaluation workflow:

1. Package the two shared intent context/ground-truth pairs.
2. Define the task registry and mode/fine-grained selection.
3. Implement shared-intent and model-specific-effect artifact resolution.
4. Refactor inference, prompts, and scoring behind the package API.
5. Implement `explainbench evaluate` and its unified result document.
6. Add focused evaluator and CLI tests.
7. Build and install a wheel in a clean environment and run an intent-only smoke test.

The detailed design and current progress are recorded in `EVALUATION_PLAN.md`.

## Current status

- [x] Agree on the product-level CLI workflow.
- [x] Choose explicit question building rather than automatic building during full evaluation.
- [x] Inspect the repository's current explanation and patch formats.
- [x] Agree on a unified JSON submission document.
- [x] Implement the submission schema and checker.
- [x] Package and verify the four shared intent artifact files.
- [x] Implement task selection and intent/effect artifact preparation.
- [x] Implement the lite evaluation engine for shared local and end-to-end intent questions.
- [x] Define the temporary and future effect-artifact directory contract.
- [x] Expose fine-grained task selection through the evaluation CLI.
- [ ] Refactor and expose the local question builder.
- [x] Implement full local evaluation using staged model-specific artifacts.
- [ ] Add clean-install and integration tests.
- [x] Add end-to-end intent and effect evaluation support.
- [x] Preserve the legacy evaluator as compatibility wrappers over the package engine.
