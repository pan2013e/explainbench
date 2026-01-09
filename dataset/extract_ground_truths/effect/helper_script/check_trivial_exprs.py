import sys
import json
from typing import Optional
from evaluation.inference import Model
from pydantic import BaseModel

class Response(BaseModel):
    trivial_expressions: Optional[list[str]]

model = Model("gpt-5.2", n=1)
file = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/step3.json"
prompt = '''You will be given a list of Python expressions but no context. Your task is to identify and return only those expressions that are trivial, meaning you do not require any program context to evaluate their values and the result is always the same constant value. If there are no trivial expressions, return null.

For example:
- Constant expressions like "42", "'hello'", or "3.14" are trivial.
- Logical expressions with short-circuit evaluation like "True and False", "True or A" or "False and A" are trivial.
- Logical expressions like "A and not A" or "A or not A" are trivial. You need to think and deduce that these expressions will always evaluate to False or True respectively, regardless of the value of A.
- Comparisons like "A == A", "3 > 2", or "'x' in 'xyz'" are trivial.

Expressions:
{expressions}
'''

with open(file, "r", encoding="utf-8") as f:
    data = json.load(f)

for agent in data:
    for instance in data[agent]:
        print(f"Processing agent={agent}, instance={instance}", file=sys.stderr)
        if not "valid_unchanged_expressions" in data[agent][instance]:
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