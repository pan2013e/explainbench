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

The example performs 1 generation for each of 3 instances across 2 intent tasks, for 6 evaluator requests. You can still override any setting from the command line, for example:

```bash
explainbench evaluate examples/submission-lite.json \
    --config examples/evaluation-lite.toml \
    --num-generations 5 \
    --workers 2 \
    --generation-workers 5
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
2. Run the following Python commands in order (make sure parameters in each script are correct).
```bash
python -m dataset.extract_ground_truths.effect.trace_step1_generate_qualname_whitelist
python -m execution.track -i all --agent AGENT_ID --max_workers WORKER_NUM
python -m dataset.extract_ground_truths.effect.trace_step2_generate_call_stack_whitelist
python -m execution.trace -i all --agent AGENT_ID --max_workers WORKER_NUM # slow
python -m dataset.extract_ground_truths.effect.build_step1
python -m dataset.extract_ground_truths.effect.build_step2
python -m dataset.extract_ground_truths.effect.build_step3
python -m dataset.extract_ground_truths.effect.build_step4
python -m dataset.extract_ground_truths.effect.build_step5
```

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
