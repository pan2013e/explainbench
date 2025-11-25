import os
import ast
import json
import shutil

from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from pydantic import BaseModel, field_validator

from evaluation.inference import Model
from execution.inspect import main as inspect_main
from execution.util import get_fail_to_pass_tests

DIR = os.path.dirname(os.path.abspath(__file__))

class Expression(BaseModel):
    expr: str
    
    @field_validator('expr')
    def validate_expr(cls, v: str):
        tree = ast.parse(v, mode='eval')
        assert isinstance(tree, ast.Expression)
        return v
    
    def as_ast(self):
        return ast.parse(self.expr, mode='eval')
    
    def eval(self,
             instance_id: str,
             agent: str,
             file_path: str,
             buggy_lineno: int,
             patched_lineno: int,
             test_id: int,
             buggy_line_count: int,
             patched_line_count: int,
             expr_id=0,
            ):
        log_dir = os.path.join(DIR, f"../../../logs/run_evaluation/inspect.{agent}.{os.getuid()}.{expr_id}/{agent}/{instance_id}")
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
            buggy_value = json.load(f)['value']
        with open(patched_path, "r") as f:
            patched_value = json.load(f)['value']
        assert buggy_value != patched_value, "The expression does not distinguish buggy and patched versions."
        
        return buggy_value, patched_value

# TODO: Check the prompt quality and improve it if necessary.
# TODO: Check if the answer candidates are too diverse
TEMPLATE = (
    "You are designing a Python expression <expr> to probe a code change. Another LLM will later be asked a question about a patch in a Python repository: \"Before the given line is executed, what is the value of <expr> before and after the patch?\" "
    "Your task is to design a single valid Python expression <expr> that best fits the question. "
    "You will be given a Python function from a repository, a specific line within that function, and the state differences at that line before and after the patch.\n\n"
    "Notes:\n"
    "1. The value of complex Python objects will be presented in JSON-serialized format, including type information and available attributes.\n"
    "2. The expressions you design should reflect such differences in values.\n"
    "3. If the given line is a return statement, use `__return__` as a special variable representing the return value.\n"
    "4. The values of the expressions should be easy for an LLM to describe, while still non-trivial to reason about. Avoid directly using complex objects or long floating-point numbers as expressions. In this case, consider using a more subtle expression that derives the desired information from these complex objects.\n"
    "5. Make sure the values of the expressions are primitive types (i.e., None, int, float, str, bool) or native collections (e.g., list, dict) of primitive types.\n\n"
    "Function:\n{code}\n\n"
    "Line:\n{line}\n\n"
    "State Differences:\n{diff}\n\n"
    "Complete Variable States before and after patch:\n"
    "Before:\n{before}\n"
    "After:\n{after}\n\n"
)

MODEL = Model("gemini/gemini-2.5-pro", n=1)

def main(code, line, diff, before, after):
    prompt = TEMPLATE.format(code=code, line=line, diff=diff, before=before, after=after)
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
