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

with open(os.path.join(DIR, "prompts/template_merged.txt"), "r") as f:
    TEMPLATE = f.read()

MODEL = Model("gpt-5.1-2025-11-13", n=1, reasoning_effort="low")

def main(code, line, diff, before, after, n_changed, n_unchanged):
    prompt = TEMPLATE.format(
        code=code,
        line=line,
        diff=diff,
        before=before,
        after=after,
        n_total=n_changed+n_unchanged,
        n_changed=n_changed,
        n_unchanged=n_unchanged
    )
    expr_list = MODEL.infer_once(prompt, ExpressionList)
    return expr_list
