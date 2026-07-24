import os
import ast
from functools import lru_cache
from typing import Callable
from pydantic import BaseModel, field_validator

from evaluation.inference import InferencePersistenceError, Model

DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = "gpt-5.2-2025-12-11"
DEFAULT_REASONING_EFFORT = "medium"

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

with open(os.path.join(DIR, "prompts/template.txt"), "r") as f:
    TEMPLATE = f.read()

@lru_cache
def get_model(
    model_id=DEFAULT_MODEL,
    reasoning_effort=DEFAULT_REASONING_EFFORT,
    env_file=None,
    max_retries=5,
):
    return Model(
        model_id,
        n=1,
        reasoning_effort=reasoning_effort,
        env_file=env_file,
        max_retries=max_retries,
    )

def main(
    prompt,
    model_id=DEFAULT_MODEL,
    reasoning_effort=DEFAULT_REASONING_EFFORT,
    env_file=None,
    max_retries=5,
    raw_response_callback: Callable[[str], None] | None = None,
):
    model = get_model(model_id, reasoning_effort, env_file, max_retries)
    expr_list = model.infer_once(
        prompt,
        ExpressionList,
        raw_response_callback=raw_response_callback,
    )
    return expr_list

def build_prompt(code, line, diff, before, after, n_changed, n_unchanged):
    return TEMPLATE.format(
        code=code,
        line=line,
        diff=diff,
        before=before,
        after=after,
        n_total=n_changed+n_unchanged,
        n_changed=n_changed,
        n_unchanged=n_unchanged
    )
