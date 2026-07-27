# ExplainBench CLI Demonstration Guide

This guide helps you demonstrate the main ExplainBench CLI functions with the files in `examples/`.

The complete demonstration takes approximately 10 minutes.

## What ExplainBench does

ExplainBench checks and evaluates explanations of code changes.

The CLI has three main functions:

1. `checker` validates the format and content of a submission.
2. `evaluate` scores explanations with an evaluator model.
3. `question-builder` builds local-effect questions from submitted patches.

## Before the demonstration

Open a terminal in the `explainbench-cli` directory.

```bash
cd explainbench-cli
```

Install the project and its locked dependencies with `uv`.

```bash
uv sync --dev
```

Confirm that the CLI is available.

```bash
uv run explainbench --version
uv run explainbench --help
```

Suggested explanation:

> The package provides one CLI for submission validation, explanation evaluation, and question construction.

## Demonstration 1: Inspect the example submission

Show the bundled full example.

```bash
jq . examples/submission-full.json
```

Point out these fields:

- `submission_id` identifies the complete submission.
- `instance_id` identifies the benchmark problem.
- `explanation` describes the code change and its purpose.
- `model_patch` contains the submitted code change.

The example contains one SymPy instance, one explanation, and one patch.

## Demonstration 2: Validate a correct submission

Run the checker on the full example.

```bash
uv run explainbench checker examples/submission-full.json
```

Expected output:

```text
Submission is valid
Submission ID: example-full
Instances: 1
Explanations: 1
Patches: 1
```

Suggested explanation:

> The checker runs locally and does not make model requests.
> It checks the JSON structure and reports a summary before an evaluation starts.

## Demonstration 3: Show a useful validation error

The bundled invalid example contains an empty explanation.

Inspect it before you run the checker.

```bash
jq . examples/submission-invalid.json
```

Run the checker on the invalid example.

```bash
uv run explainbench checker examples/submission-invalid.json
echo "Exit code: $?"
```

Expected output:

```text
Submission is invalid
- instances[0].explanation: must be a nonempty string
Exit code: 1
```

Suggested explanation:

> The checker reports the exact invalid field and returns a nonzero exit code.
> This behavior makes the checker suitable for scripts and continuous integration.

## Demonstration 4: Explain the evaluation tasks

ExplainBench supports four evaluation tasks:

| Task | What it measures |
| --- | --- |
| `e2e.intent` | Whether the explanation describes the overall intent of the change. |
| `e2e.effect` | Whether the explanation describes the overall effect of the change. |
| `local.intent` | Whether the explanation describes the intent near the changed code. |
| `local.effect` | Whether the explanation describes the effect near the changed code. |

The full example includes the question artifacts required by the effect tasks.

Show the available artifacts.

```bash
find examples/question-artifacts -type f | sort
```

Show the full evaluation configuration.

```bash
sed -n '1,160p' examples/evaluation-full.toml
```

Point out that the configuration selects full mode, uses one model generation, and writes a versioned JSON result.

## Demonstration 5: Run a full evaluation

This command makes paid model requests.

The bundled full example contains one instance and four tasks, so the default example configuration makes four evaluator requests.

Set the API credential required by the configured model provider.

```bash
export OPENAI_API_KEY="YOUR_API_KEY"
```

Do not display the real key during the presentation.

Run the evaluation.

```bash
uv run explainbench evaluate examples/submission-full.json \
  --config examples/evaluation-full.toml
```

The result is written to `results/full-example.json`.

The final terminal output should include:

```text
Evaluation complete
Submission ID: example-full
Tasks: e2e.intent, e2e.effect, local.intent, local.effect
Results: results/full-example.json
```

Suggested explanation:

> ExplainBench validates the submission and question artifacts before it sends model requests.
> It evaluates each selected task and stores the scores, counts, predictions, model settings, and token usage in one result document.

## Demonstration 6: Inspect the evaluation result

Show a compact summary.

```bash
jq '{
  submission_id,
  selection,
  model: .evaluator.model,
  token_usage: .evaluator.token_usage,
  tasks: (.tasks | map_values({
    statistics,
    counts
  }))
}' results/full-example.json
```

Show the complete result if your colleague wants more detail.

```bash
jq . results/full-example.json
```

Point out these result sections:

- `selection` records the selected mode and tasks.
- `evaluator` records the model settings and token usage.
- `statistics` contains the mean score and standard error for each task.
- `counts` shows evaluated, skipped, and failed instances.
- `instances` contains the model predictions and scores.
- `failures` records errors without hiding successful results.

## Demonstration 7: Show checkpoint recovery

ExplainBench can retain compatible completed work when an evaluation stops before completion.

Use `--resume` when you restart an interrupted evaluation.

```bash
uv run explainbench evaluate examples/submission-full.json \
  --config examples/evaluation-full.toml \
  --resume
```

Suggested explanation:

> Resume support avoids repeating compatible completed model work after an interruption.
> ExplainBench removes the checkpoint after all work completes successfully.

Do not run this command after a successful evaluation only to demonstrate speed.

A successful evaluation has no remaining checkpoint to reuse.

## Demonstration 8: Introduce the question builder

List the local-effect construction stages.

```bash
uv run explainbench question-builder local stages
```

The command shows the ten stages from patch analysis through artifact export.

Show the complete pipeline command without running it during a short presentation.

```bash
uv run explainbench question-builder local run examples/submission-full.json \
  --workspace .explainbench/builds/example-full \
  --output examples/generated-question-artifacts \
  --resume
```

Inspect a pipeline workspace with:

```bash
uv run explainbench question-builder local status \
  --workspace .explainbench/builds/example-full
```

The complete builder can require Docker, benchmark repositories, model credentials, and significant execution time.

The bundled `examples/question-artifacts/` directory lets you demonstrate full evaluation without running the complete builder first.

Suggested explanation:

> The question builder analyzes a submitted patch, observes program behavior, finds useful state differences, constructs answer choices, and exports evaluator-compatible artifacts.
> Its workspace contains checkpoints, traces, logs, and audit information.

## Optional shorter evaluation

Use the lite example when you want to demonstrate only the two intent tasks.

```bash
uv run explainbench checker examples/submission-lite.json

uv run explainbench evaluate examples/submission-lite.json \
  --config examples/evaluation-lite.toml
```

This evaluation uses three instances and one generation for each of two tasks.

It makes six evaluator requests and writes `results/lite-example.json`.

## Recommended presentation order

1. Explain the three CLI functions.
2. Inspect `examples/submission-full.json`.
3. Run a successful checker demonstration.
4. Run the invalid-submission demonstration.
5. Explain the four evaluation tasks.
6. Run the full evaluation.
7. Inspect the compact result summary.
8. List the question-builder stages.
9. Close with validation, auditability, and checkpoint recovery.

## Key points to conclude with

- ExplainBench uses a clear and machine-readable submission format.
- The checker gives fast local feedback before paid evaluation starts.
- Lite mode evaluates explanation intent.
- Full mode evaluates intent and effect at end-to-end and local levels.
- Evaluation results include scores, failures, configuration, and token usage.
- Checkpoints support recovery from interrupted work.
- The question builder produces submission-specific local-effect artifacts.

## Troubleshooting

If the environment is missing or out of date, synchronize it again.

```bash
uv sync --dev
```

If the evaluator reports an authentication error, confirm that the provider API key is available.

```bash
test -n "$OPENAI_API_KEY" && echo "OPENAI_API_KEY is set"
```

If `jq` is not installed, use Python to display a JSON file.

```bash
python -m json.tool examples/submission-full.json
```

Use CLI help to inspect all available options.

```bash
uv run explainbench checker --help
uv run explainbench evaluate --help
uv run explainbench question-builder local --help
```
