import argparse
import json
import os
import sys
from typing import Optional

from evaluation.inference import Model
from pydantic import BaseModel

class Response(BaseModel):
    trivial_expressions: Optional[list[str]]

model = Model("gpt-5.2", n=1)
DEFAULT_INPUT_FILE = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/step3.json"
DEFAULT_OUTPUT_FILE = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/trivial_exprs.json"
prompt = '''You will be given a list of Python expressions but no context. Your task is to identify and return only those expressions that are trivial, meaning you do not require any program context to evaluate their values and the result is always the same constant value. If there are no trivial expressions, return null.

For example:
- Constant expressions like "42", "'hello'", or "3.14" are trivial.
- Logical expressions with short-circuit evaluation like "True and False", "True or A" or "False and A" are trivial.
- Logical expressions like "A and not A" or "A or not A" are trivial. You need to think and deduce that these expressions will always evaluate to False or True respectively, regardless of the value of A.
- Comparisons like "A == A", "3 > 2", or "'x' in 'xyz'" are trivial.

Expressions:
{expressions}
'''

parser = argparse.ArgumentParser(description="Identify trivial expressions and save results as JSON.")
parser.add_argument("--input", default=DEFAULT_INPUT_FILE, help="Path to step3.json input file.")
parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE, help="Path to write JSON results.")
args = parser.parse_args()

with open(args.input, "r", encoding="utf-8") as f:
    data = json.load(f)

if os.path.exists(args.output):
    with open(args.output, "r", encoding="utf-8") as f:
        results: dict[str, dict[str, list[str]]] = json.load(f)
else:
    results = {}

for agent in data:
    for instance in data[agent]:
        if agent in results and instance in results[agent]:
            continue
        print(f"Processing agent={agent}, instance={instance}", file=sys.stderr)
        if "valid_unchanged_expressions" not in data[agent][instance]:
            continue
        valid_unchanged = data[agent][instance]["valid_unchanged_expressions"]
        if len(valid_unchanged) == 0:
            print(f"> Empty valid_unchanged_expressions: agent={agent}, instance={instance}")
            continue
        message = prompt.format(expressions="\n".join(valid_unchanged))
        answer = model.infer_once(message, Response)
        if answer.trivial_expressions:
            print(f"> Suggested trivial expressions for agent={agent}, instance={instance}")
            for expr in answer.trivial_expressions:
                print(f">>  {expr}")
            results.setdefault(agent, {})[instance] = answer.trivial_expressions
        else:
            results.setdefault(agent, {})[instance] = []

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, sort_keys=True)
