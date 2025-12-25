import os
import ast
import re
from pydantic import BaseModel, field_validator

from evaluation.inference import Model
from dataset.extract_ground_truths.effect.postprocessing_util import iter_diff_items

DIR = os.path.dirname(os.path.abspath(__file__))

def convert_to_valid_arg(expr: str):
    expr = expr.strip()
    if (
        expr.startswith("`") and expr.endswith("`")
        or expr.startswith('"') and expr.endswith('"')
        or expr.startswith("'") and expr.endswith("'")
    ):
        expr = expr[1:-1].strip()
    return expr

class Expression(BaseModel):
    expr: str
    
    @field_validator('expr')
    @classmethod
    def validate_expr(cls, v: str):
        tree = ast.parse(v, mode='eval')
        assert isinstance(tree, ast.Expression)
        assert not isinstance(tree.body, ast.Constant)
        return convert_to_valid_arg(v)

class ExpressionList(BaseModel):
    expressions: list[Expression]

with open(os.path.join(DIR, "prompts/template_changed.txt"), "r") as f:
    TEMPLATE_CHANGED = f.read()

with open(os.path.join(DIR, "prompts/template_unchanged.txt"), "r") as f:
    TEMPLATE_UNCHANGED = f.read()

MODEL = Model("gpt-5.1-codex", n=1, reasoning_effort="medium")

# NOTE: Currently, it is possibel that input diff contains more than 1. In this case, this function outputs the first object.
# It can be modified in the future\
_BRACKETED_NAME_RE = re.compile(r"\[['\"]([^'\"]+)['\"]\]")
def extract_seed_exp(input_diff):

    def extract_var_name(full_path: str, key_idx) -> str:
        tokens = _BRACKETED_NAME_RE.findall(str(full_path))
        if len(tokens) > key_idx:
            return tokens[key_idx]
        return "" 

    seed_expr = []
    for change_kind, full_path, payload in iter_diff_items(input_diff):

        # default pattern: root[seen_variables][var_name]
        var_name = extract_var_name(full_path, 1)
        
        # another pattern: root[return_value] or root[exception_value]
        if var_name == "":
            var_name = extract_var_name(full_path, 0)

        if var_name == "return_value":
            var_name = "__return__"
            return var_name

        elif var_name == "exception_value":
            var_name = "__exception__"

        seed_expr.append(var_name)
    return seed_expr[0]

def main(code, line, diff, before, after, should_change, n_output, changed_expressions=None):
    if should_change:
        prompt = TEMPLATE_CHANGED.format(
            code=code,
            line=line,
            diff=diff,
            before=before,
            after=after,
            n_output=n_output,
            seed_expression=extract_seed_exp(diff)
        )
    else:
        prompt = TEMPLATE_UNCHANGED.format(
            code=code,
            line=line,
            diff=diff,
            before=before,
            after=after,
            n_output=n_output,
            changed_expressions=changed_expressions if changed_expressions else ""
        )
    expr_list = MODEL.infer_once(prompt, ExpressionList)
    return expr_list
