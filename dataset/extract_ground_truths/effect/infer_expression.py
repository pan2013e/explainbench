import os
import ast
import json
import shutil
from pprint import pprint
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from pydantic import BaseModel, field_validator

from evaluation.inference import Model
from execution.inspect import main as inspect_main
from execution.util import get_fail_to_pass_tests

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

def check_change(buggy_value, buggy_exc, patched_value, patched_exc):
    # Special check for "None.attr vs obj.attr" case
    if buggy_exc is None and patched_exc is not None:
        exc_stage, exc_type, exc_msg = patched_exc['stage'], patched_exc['type'], patched_exc['message']
        if (
            exc_stage == 'evaluation'
            and exc_type == 'AttributeError'
            and 'NoneType' in exc_msg
        ):
            return
        raise AssertionError("Exception occurred in patched inspection")
    elif buggy_exc is not None and patched_exc is None:
        exc_stage, exc_type, exc_msg = buggy_exc['stage'], buggy_exc['type'], buggy_exc['message']
        if (
            exc_stage == 'evaluation'
            and exc_type == 'AttributeError'
            and 'NoneType' in exc_msg
        ):
            return
        raise AssertionError("Exception occurred in buggy inspection")
    elif buggy_exc is not None and patched_exc is not None:
        raise AssertionError("Exception occurred in both buggy and patched inspection")
    else:
        # both exc is None
        assert buggy_value != patched_value, "Expression does not distinguish buggy and patched versions."

def check_no_change(buggy_value, buggy_exc, patched_value, patched_exc):
    assert buggy_exc is None, "Exception occurred in buggy inspection"
    assert patched_exc is None, "Exception occurred in patched inspection"
    assert buggy_value == patched_value, "Expression unexpectedly distinguishes buggy and patched versions."

class Expression(BaseModel):
    expr: str
    
    @field_validator('expr')
    @classmethod
    def validate_expr(cls, v: str):
        tree = ast.parse(v, mode='eval')
        assert isinstance(tree, ast.Expression)
        assert not isinstance(tree.body, ast.Constant)
        return convert_to_valid_arg(v)
    
    def validate_effect(self,
             instance_id: str,
             agent: str,
             file_path: str,
             buggy_lineno: int,
             patched_lineno: int,
             test_id: int,
             buggy_line_count: int,
             patched_line_count: int,
             before_or_after: str,
             should_change=True,
             expr_id=0,
            ):
        log_dir = "/home/yusuf/explainbench/dataset/extract_ground_truths/effect/logs/run_evaluation/inspect.20250805_openhands-Qwen3-Coder-480B-A35B-Instruct.1020.0/20250805_openhands-Qwen3-Coder-480B-A35B-Instruct/astropy__astropy-12907"
        if os.path.exists(log_dir):
            shutil.rmtree(log_dir)
        
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            inspect_main([
                "--instance_id", instance_id,
                "--agent", agent,
                "--bp-file", file_path,
                "--pre-bp-line", str(buggy_lineno),
                "--post-bp-line", str(patched_lineno),
                "--expr", self.expr,
                "--expr-id", str(expr_id),
                "--pre-count", str(buggy_line_count),
                "--post-count", str(patched_line_count),
                "--inspector-mode", before_or_after,
            ])
        
        test_name = get_fail_to_pass_tests(instance_id)[test_id]
        buggy_path = os.path.join(log_dir, f"buggy_traces/{test_name}.jsonl")
        patched_path = os.path.join(log_dir, f"patched_traces/{test_name}.jsonl")
        if not os.path.exists(buggy_path) or not os.path.exists(patched_path):
            print(f"Inspection results not found for {instance_id}, test {test_name}")
            print(f"Inspection stdout:\n{stdout.getvalue()}")
            print(f"Inspection stderr:\n{stderr.getvalue()}")
            raise RuntimeError("Inspection failed, results not found.")
        
        with open(buggy_path, "r") as f:
            buggy_inspect = json.load(f)
            buggy_value = buggy_inspect['value']
            buggy_inspect_exc = buggy_inspect['exception']
        with open(patched_path, "r") as f:
            patched_inspect = json.load(f)
            patched_value = patched_inspect['value']
            patched_inspect_exc = patched_inspect['exception']
        pprint(buggy_inspect)
        pprint(patched_inspect)
        
        if should_change:
            check_change(buggy_value, buggy_inspect_exc, patched_value, patched_inspect_exc)
        else:
            check_no_change(buggy_value, buggy_inspect_exc, patched_value, patched_inspect_exc)


with open(os.path.join(DIR, "prompts/template_changed.txt"), "r") as f:
    TEMPLATE_CHANGED = f.read()

with open(os.path.join(DIR, "prompts/template_unchanged.txt"), "r") as f:
    TEMPLATE_UNCHANGED = f.read()


MODEL = Model("gemini/gemini-2.5-pro", n=1)

def main(code, line, diff, before, after, 
         should_change=True, existing_changed=[], existing_unchanged=[]):
    template = TEMPLATE_CHANGED if should_change else TEMPLATE_UNCHANGED
    prompt = template.format(code=code, line=line, diff=diff, before=before, after=after)
    print(prompt)
    breakpoint()
    expr = MODEL.infer_once(prompt, Expression)
    return expr

if __name__ == "__main__":
    code = '''def is_separable(transform):
    if transform.n_inputs == 1 and transform.n_outputs > 1:
        is_separable = np.array([False] * transform.n_outputs).T
        return is_separable
    separable_matrix = _separable(transform)
    is_separable = separable_matrix.sum(1)
    is_separable = np.where(is_separable != 1, False, True)
    return is_separable'''
    line = "separable_matrix = _separable(transform)"
    diff = "omitted, please see the full context"
    before = "{'separable_matrix': {'py/object': 'numpy.ndarray', 'dtype': 'float64', 'values': [[1.0, 1.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0]]}"
    after = "{'separable_matrix': {'py/object': 'numpy.ndarray', 'dtype': 'float64', 'values': [[1.0, 1.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]}"
    print(main(code, line, diff, before, after))
