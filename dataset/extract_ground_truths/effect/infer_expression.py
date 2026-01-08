import os
import ast
import re
from pydantic import BaseModel, field_validator

from evaluation.inference import Model
from dataset.extract_ground_truths.effect.postprocessing_util import iter_diff_items

DIR = os.path.dirname(os.path.abspath(__file__))

class Expression(BaseModel):
    expr: str
    
    @field_validator('expr')
    @classmethod
    def validate_expr(cls, v: str):
        tree = ast.parse(v, mode='eval')
        assert isinstance(tree, ast.Expression)
        assert not isinstance(tree.body, ast.Constant)
        return v

class ExpressionList(BaseModel):
    expressions: list[Expression]

with open(os.path.join(DIR, "prompts/template_changed.txt"), "r") as f:
    TEMPLATE_CHANGED = f.read()

with open(os.path.join(DIR, "prompts/template_unchanged.txt"), "r") as f:
    TEMPLATE_UNCHANGED = f.read()

MODEL = Model("gpt-5.1-2025-11-13", n=1, reasoning_effort="low")

def main(code, line, diff, before, after, should_change, n_output, changed_expressions=None):
    if should_change:
        prompt = TEMPLATE_CHANGED.format(
            code=code,
            line=line,
            diff=diff,
            before=before,
            after=after,
            n_output=n_output,
        )
    else:
        prompt = TEMPLATE_UNCHANGED.format(
            code=code,
            line=line,
            diff=diff,
            before=before,
            after=after,
            n_output=n_output,
        )
    expr_list = MODEL.infer_once(prompt, ExpressionList)
    return expr_list
