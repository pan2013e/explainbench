# Temporary documentation

## Usage

1. Install dependencies in `requirements.txt`.
2. Create `.env` file in the root directory and add your API keys in `KEY=VALUE` format.
3. Run `python -m evaluation.main` with args in the root directory to execute the evaluation.
```
usage: evaluation.main [-h] -a AGENT [-m MODEL] [-n NUM_GENERATIONS] [-go] [-eo] task

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

Available tasks: ...
```
4. Results will be saved in the `results/` directory.
