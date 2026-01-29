# Documentation for Replication Package

This replication package is shared privately for double anonymous review. 

## Directory structure

```
.
├── audit_agent
├── dataset
├── evaluation
├── execution
├── pbt-generator
├── pyproject.toml
├── py-tracer
├── README.md
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

Install the dependencies listed in `pyproject.toml`

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

1. Setup `pbt-generator` submodule. 
2. Run ...

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
