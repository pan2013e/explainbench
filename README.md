# Documentation for Replication Package

This replication package is shared privately for double anonymous review. 

## ExplainBench package CLI

After installing the package from the repository or a built wheel, validate a submission with:

```bash
explainbench checker submission.json
```

Run the two shared intent evaluations with:

```bash
explainbench evaluate submission.json \
    --mode lite \
    --model gpt-5-mini-2025-08-07 \
    --num-generations 5 \
    --workers 10 \
    --output results.json
```

Evaluation can instead be controlled by a versioned TOML file:

```toml
schema_version = 1

[selection]
mode = "lite"
# Alternatively: tasks = ["local.intent", "e2e.effect"]

[evaluator]
model = "gpt-5-mini-2025-08-07"
num_generations = 5
instance_workers = 10
generation_workers = 5
temperature = 1.0
top_p = 1.0
max_tokens = 8192
max_retries = 5

[paths]
output = "results.json"
# artifacts_dir = "question-artifacts"

[environment]
env_file = ".env"
```

Use it with:

```bash
explainbench evaluate submission.json --config evaluation.toml
```

Explicit CLI options override values from the config, and omitted values use package defaults. Paths written in the config are resolved relative to the config file. Effect tasks additionally require `paths.artifacts_dir` or `--artifacts-dir` containing the model-specific question artifacts.

API credentials should be exported as provider environment variables or placed in the configured dotenv file. Do not put credentials directly in the TOML file.

### Runnable lite example

The repository includes a three-instance submission containing real explanations from `dataset/explanations/dataset.json` under the `openhands_gpt-5-mini` entry, together with a starter config. It uses the package defaults except for one generation instead of five, to limit API cost:

- [`examples/submission-lite.json`](examples/submission-lite.json)
- [`examples/evaluation-lite.toml`](examples/evaluation-lite.toml)

Validate and evaluate them with:

```bash
explainbench checker examples/submission-lite.json
explainbench evaluate examples/submission-lite.json \
    --config examples/evaluation-lite.toml
```

Before inference begins, the command prints the resolved task selection, evaluator, generation count, and output path. Interactive terminals also show a tqdm progress bar for each task with completed/failed instance counts and cumulative token usage. Use `--no-progress` to suppress the bars.

Every CLI evaluation automatically writes completed task-instances to a sidecar checkpoint next to the requested output. For example, `results/lite-example.json` uses `results/lite-example.json.checkpoint.jsonl`. If the process is interrupted, rerun the same evaluation with `--resume`:

```bash
explainbench evaluate examples/submission-lite.json \
    --config examples/evaluation-lite.toml \
    --resume
```

Resume validates the submission, task selection, question artifacts, model, generation count, sampling settings, and token limit before reusing work. Concurrency and retry counts may be changed. Completed task-instances are skipped, while failed and interrupted instances run again. A clean completion removes the checkpoint; a run with failures retains it for another retry. Running without `--resume` starts fresh and replaces any checkpoint for that output path.

The configured output path is relative to the TOML file. This example uses `../results/lite-example.json`, so it writes `results/lite-example.json` under the repository root. An explicit CLI path overrides it and is interpreted relative to the current working directory:

```bash
explainbench evaluate examples/submission-lite.json \
    --config examples/evaluation-lite.toml \
    --output ./my-results.json
```

The example performs 1 generation for each of 3 instances across 2 intent tasks, for 6 evaluator requests. You can still override any setting from the command line, for example:

```bash
explainbench evaluate examples/submission-lite.json \
    --config examples/evaluation-lite.toml \
    --num-generations 5 \
    --workers 2 \
    --generation-workers 5
```

### Runnable full example

The repository also includes a one-instance full-mode example derived from the existing `20250807_mini-v1.7.0_gpt-5-mini` artifacts. It demonstrates the exact directory contract that `question-builder` will eventually produce:

- [`examples/submission-full.json`](examples/submission-full.json)
- [`examples/evaluation-full.toml`](examples/evaluation-full.toml)
- [`examples/question-artifacts`](examples/question-artifacts)

Run all four question types—local/end-to-end intent and effect—with:

```bash
explainbench checker examples/submission-full.json
explainbench evaluate examples/submission-full.json \
    --config examples/evaluation-full.toml
```

The example performs one evaluator request for each of the four tasks and writes `results/full-example.json`. To try only one effect task, override the full-mode selection:

```bash
explainbench evaluate examples/submission-full.json \
    --config examples/evaluation-full.toml \
    --task local.effect

explainbench evaluate examples/submission-full.json \
    --config examples/evaluation-full.toml \
    --task e2e.effect
```

## Directory structure

```
.
├── audit_agent
├── dataset
├── evaluation
├── execution
├── pbt-generator
├── py-tracer
├── results
└── supplementary_materials
```

- `audit_agent/`: Contains the code for ExplanationAuditAgent, which performs additional differential testing to validate and refine agent explanations.
- `dataset/`: Contains benchmark data and part of the ExplainBench framework for automatically collecting explanations, questions, context, and ground truths.
- `evaluation/`: Contains the evaluation scripts.
- `execution/`: Contains the instrumentation and test execution framework for (1) running developer tests and tracing their behavior (2) and running PBTs.
- `pbt-generator/`: Contains the rest part of the ExplainBench framework for automatically generating PBTs for end-to-end questions.
- `py-tracer/`: Contains the code for execution tracing and object serialization.
- `results/`: Contains evaluation results.
- `supplementary_materials/`: Contains supplementary materials as mentioned in Section 8.1 of the paper.

## Artifact 1: ExplainBench

> ExplainBench is an evaluation framework that automatically evaluates the quality of code explanations from agents.

### Evaluation setup

Install the dependencies listed in `pyproject.toml`.

### How to run evaluation

1. Prepare API keys for LLM access. Either export to environment variables before running, or create a `.env` file in the root directory and add your API keys in `KEY=VALUE` format. Refer to litellm documentation (https://docs.litellm.ai/docs/set_keys) for available `KEY` names.
2. Run `python -m evaluation.main` with args in the root directory to execute the evaluation.
```
usage: evaluation.main [-h] -a AGENT [-m MODEL] [-n NUM_GENERATIONS] [-go] [-eo] [--gen-workers GEN_WORKERS] [--use-audit-expl] task

positional arguments:
  task                  Evaluation task to run

options:
  -h, --help            show this help message and exit
  -a AGENT, --agent AGENT
                        ID of agent producing the explanations
  -m MODEL, --model MODEL
                        LLM used for question answering
  -n NUM_GENERATIONS, --num-generations NUM_GENERATIONS
                        Number of generations per instance
  -go, --gen-only       Only generate predictions
  -eo, --eval-only      Only evaluate existing predictions
  --gen-workers GEN_WORKERS
                        Number of parallel workers for generation
  --use-audit-expl      Use explanations from audit agent

Available tasks: e2e.effect, e2e.intent, local.effect, local.intent
```
3. Results will be saved in the `results/` directory.

### How to replicate data collection or extend to new agents

#### Explanation extraction

See `dataset/explanations/README.md`.

#### End-to-end questions

Note that PBT generation is expensive. If you would like to skip PBT generation, go to step 5.

1. Setup `pbt-generator` submodule. 
2. Setup AutoCodeRover as described in pbt-generator/README.md.
3. In the `pbt-generator` directory, run the command below to generate PBTs. (\<SWE-bench-path\> is described in pbt-generator/README.md.)
```bash
PYTHONPATH=. python app/main.py swe-bench \
    --model gpt-5.2-2025-12-11 \
    --setup-map <SWE-bench-path>/setup_result/setup_map.json \
    --tasks-map <SWE-bench-path>/setup_result/tasks_map.json \
    --output-dir output \
    --task-list-file ../instances.txt
```
4. In the `pbt-generator` directory, run the following in order to label the expected behavior expression of the PBTs.
```bash
python scripts/gather_test_data.py \
    --output_dir output \
    --all_bug_list ../instances.txt \
    --save_file gathered.jsonl
python scripts/annotate.py
    --input_file gathered.jsonl
    --save_file annotated.json
```
5. Run the following command in this directory (if you have skipped PBT generation, use `./dataset/context/raw_pbts.json` instead of `./pbt-generator/annotated.json`:
```bash
python -m execution.pbt.patch_runner \
    --swebench_pred_file [PATH_TO_PATCH_FILE]
    --pbt_file ./pbt-generator/annotated.json
    --workers [WORKER_NUM]
```

#### Local questions

1. Run `pip install -e py-tracer[all]`
2. Run the canonical commands in order. Every command now accepts explicit submission, instance, input, output, worker, and run-path options; the example below shows one agent and one instance.
```bash
python -m dataset.extract_ground_truths.effect.trace_step1_generate_qualname_whitelist \
    --agent AGENT_ID \
    --predictions-path PATH_TO_PATCH_FILE \
    --instance-ids INSTANCE_ID \
    --repos-root PATH_TO_REPOSITORY_CACHE \
    --output-path WORK_DIR/allowed_qualnames.json

python -m execution.track \
    --agent AGENT_ID \
    --predictions-path PATH_TO_PATCH_FILE \
    --allowed-qualnames-path WORK_DIR/allowed_qualnames.json \
    --instance-ids INSTANCE_ID \
    --run-id track.AGENT_ID \
    --max-workers WORKER_NUM

python -m dataset.extract_ground_truths.effect.trace_step2_generate_call_stack_whitelist \
    --agent AGENT_ID \
    --instance-ids INSTANCE_ID \
    --targets-json WORK_DIR/allowed_qualnames.json \
    --root-path 'ABSOLUTE_REPO_PATH/logs/run_evaluation/track.AGENT_ID/{agent_name}/{instance_id}' \
    --output-path WORK_DIR/allowed_functions.json

python -m execution.trace \
    --agent AGENT_ID \
    --predictions-path PATH_TO_PATCH_FILE \
    --allowed-functions-path WORK_DIR/allowed_functions.json \
    --instance-ids INSTANCE_ID \
    --run-id trace.AGENT_ID \
    --max-workers WORKER_NUM

python -m dataset.extract_ground_truths.effect.build_step1 \
    --agent AGENT_ID \
    --instance-ids INSTANCE_ID \
    --trace-root-template ABSOLUTE_REPO_PATH/logs/run_evaluation/trace.AGENT_ID/AGENT_ID \
    --output-path WORK_DIR/step1.json

python -m dataset.extract_ground_truths.effect.build_step2 \
    --agent AGENT_ID \
    --instance-ids INSTANCE_ID \
    --step1-path WORK_DIR/step1.json \
    --predictions-path PATH_TO_PATCH_FILE \
    --output-path WORK_DIR/step2.json

python -m dataset.extract_ground_truths.effect.build_step3 \
    --execute \
    --agent AGENT_ID \
    --instance-ids INSTANCE_ID \
    --step2-path WORK_DIR/step2.json \
    --gold-step2-path PATH_TO_STEP2_GOLD_JSON \
    --gold-output-path PATH_TO_STEP3_GOLD_JSON \
    --predictions-path PATH_TO_PATCH_FILE \
    --inspection-run-id-template 'inspect.{agent}.{expr_id}'

python -m dataset.extract_ground_truths.effect.build_step3 \
    --validate \
    --agent AGENT_ID \
    --instance-ids INSTANCE_ID \
    --step2-path WORK_DIR/step2.json \
    --gold-step2-path PATH_TO_STEP2_GOLD_JSON \
    --gold-output-path PATH_TO_STEP3_GOLD_JSON \
    --inspection-run-id-template 'inspect.{agent}.{expr_id}' \
    --logs-root ABSOLUTE_REPO_PATH/logs/run_evaluation \
    --output-path WORK_DIR/step3.json

python -m dataset.extract_ground_truths.effect.build_step4 \
    --agent AGENT_ID \
    --instance-ids INSTANCE_ID \
    --step3-path WORK_DIR/step3.json \
    --output-path WORK_DIR/step4.json

python -m dataset.extract_ground_truths.effect.build_step5 \
    --kind effect \
    --agent AGENT_ID \
    --instance-ids INSTANCE_ID \
    --effect-step4-path WORK_DIR/step4.json \
    --context-dir WORK_DIR/question-artifacts/context \
    --ground-truth-dir WORK_DIR/question-artifacts/ground_truths
```

Use `python -m MODULE --help` to see the complete interface for any stage. In particular, model selection and candidate counts are configured by `build_step2`, while timeouts, concurrency, MMR selection, random seed, and parameter truncation are exposed by their respective commands.

SWE-bench docker instances will be created and run during these steps, so there is a minimum disk space requirement (please refer to https://github.com/SWE-bench/SWE-bench). In resource-limited machines, please reduce the parallelism to avoid crashes or docker timeouts.

After running these scripts in order, there should be `local_intent.json` and `local_effect__{AGENT_ID}.json` under `dataset/context`. Extending to new agents does not produce different `local_intent.json`.

### How to extend evaluation to new questions

1. In `evaluation/schema.py`, create a new class inheriting from `BaseModel`. This defines the output schema of the LLM's response. Make sure the class is JSON-serializable.
2. In `evaluation/tasks.py`, create a new class inheriting from `Task`. Implement the three following fields and methods:

```python
from evaluation import schema

class MyTask(Task[schema.MySchema]):
    #                    ^^^^^^^^ Class defined in step 1
    QUESTION = ... # The question to ask the LLM
    SCHEMA = schema.MySchema # Class defined in step 1
    CTX_AGENT_SPECIFIC = False # If the context in the prompts is agent-specific

    @staticmethod
    def eval(pred: list[schema.MySchema], gt: dict): # Should return list[float]
        '''
        Batched evaluation function.

        Args:
        - pred: List of model predictions with length n (repeated n times for a dataset instance).
        - gt: Ground truth data for the dataset instance.
        '''
        # Evaluation logic here
        pass
```

The task class is versatile, and the user can implement other helper methods to format the question for different dataset instances. See `Task.Effect` class in `evaluation/task.py`.

3. Prepare context and ground truth files. If `CTX_AGENT_SPECIFIC` is set to `False`, context and ground truths will be loaded from `dataset/{context | ground_truths}/{MyTask.__qualname__.replace('.', '_')}.json`; otherwise it will be loaded from `dataset/{context | ground_truths}/{MyTask.__qualname__.replace('.', '_')}__{AGENT_ID}.json`.


## Artifact 2: ExplanationAuditAgent

> ExplanationAuditAgent is an agent that runs additional tests to validate and refine agent explanations.

See `audit_agent/README.md`
