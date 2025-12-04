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
        assert buggy_inspect_exc is None, "Other exception occurred in buggy inspection"
        assert patched_inspect_exc is None, "Other exception occurred in patched inspection"
        assert buggy_value != patched_value, "The expression does not distinguish buggy and patched versions."

# TODO: Check the prompt quality and improve it if necessary.
# TODO: Check if the answer candidates are too diverse


# TODO: Modify the prompt. Let the llm generate an expression that <change/or not change>
# We do the prompting multiple times to get n choices
# Within, we can configure the n_changes

# We cannot make some options too trivial
 

TEMPLATE = (
    # "You are designing a Python expression <expr> to probe a code change. Another LLM will later be asked a question about a patch in a Python repository: \"Before the given line is executed, what is the value of <expr> before and after the patch?\" "
    # "Your task is to design a single valid Python expression <expr> that best fits the question. "
    # "You will be given a Python function from a repository, a specific line within that function, and the state differences at that line before and after the patch.\n\n"
    # "Notes:\n"
    # "1. The value of complex Python objects will be presented in JSON-serialized format produced by the jsonpickle library, including type information and some available attributes.\n"
    # "2. The expressions you design should reflect such differences in values.\n"
    # "3. When `__return__` is available in the local variable list, it is a special variable representing the return value.\n"
    # "4. Sometimes the code execution of one version may fail to reach the given line due to an exception raised earlier. In this case, the crashed line will also be provided. If two lines differ, you only need to reason about the normally executed line.\n"
    # "5. The values of the expressions should be easy for an LLM to describe, while still non-trivial to reason about. Avoid directly using complex objects or long floating-point numbers as expressions. In this case, consider using a more subtle expression that derives the desired information from these complex objects.\n"
    # "6. Make sure the values of the expressions are primitive types (i.e., None, int, float, str, bool) or native collections (e.g., list, dict) of primitive types.\n\n"
    # "Function:\n{code}\n\n"
    # "Line:\n{line}\n\n"
    # "State Differences:\n{diff}\n\n"
    # "Complete Variable States before and after patch:\n"
    # "Before:\n{before}\n"
    # "After:\n{after}\n\n"

"""
You are designing a Python expression `<expr>` to probe a code change.
Another LLM will later be given several candidate expressions, including your `<expr>`, and asked to choose which ones produce different values before and after the patch.

### Inputs
You will be given:
- A Python function from a repository
- A specific line within that function
- State differences at that line before and after the patch
- Complete variable states before and after the patch
- A list of existing expressions that are already known to produce different values (this list may be empty)

### Task
Produce exactly one additional Python expression `<expr>` that:
- Evaluates to **different values** in the “before” and “after” states, and
- Is **non-trivial** (see structural constraints below), and
- Is **not** an obvious transformation of any existing expression.

Your output must be only a valid Python expression (no quotes, no explanation).

### Hard semantic constraints
1. `<expr>` MUST evaluate to **different values** in the “before” and “after” versions.
2. `<expr>` MUST be valid and MUST NOT raise any exceptions (IndexError, KeyError, AttributeError, TypeError, etc.) in either state.
3. `<expr>` may refer only to variables, attributes, or values available in the provided function.
4. The final value of `<expr>` must be a primitive (`None`, `int`, `float`, `str`, `bool`) or a built-in collection (`list`, `dict`, `tuple`, `set`) whose elements are all primitives.

### Structural constraints
1. `<expr>` MUST NOT be just a bare variable, attribute, index access, or a single literal (e.g., `foo`, `obj.x`, `lst[0]`, `0`).
2. `<expr>` may use at least one of:
   * An arithmetic operator (`+`, `-`, `*`, `/`, `//`, `%`, `**`)
   * A comparison (`==`, `!=`, `<`, `<=`, `>`, `>=`)
   * A logical operator (`and`, `or`, `not`)
   * A non-trivial use of an aggregator/predicate (`len`, `sum`, `min`, `max`, `any`, `all`, `sorted`, or a comprehension)
3. Prefer deriving a **property or predicate** of changed data rather than returning the changed primitive value itself.

### Relationship to existing expressions
1. `<expr>` MUST NOT be identical to any existing expression.
2. Avoid trivial rewrites of existing expressions, such as:
   * Simple negations (`not existing_expr`).
   * Adding/subtracting a constant (`existing_expr + 1`).
   * Simple casting/wrapping (`str(existing_expr)`, `[existing_expr]`).
   * Reordering or cosmetically reformatting the same computation.
   * Returning the same underlying changed primitive via a simple aggregator on the same object.
3. Prefer expressions that:
   * Use a different attribute, index, or aggregation over a changed object, or
   * Combine or compare two or more variables/attributes to expose a related but distinct aspect of the state.

### Safety guidance
When building `<expr>`, ensure it is safe in both states:
* For lists/tuples: only use index `i` if it is valid in both states; otherwise, use `len(...)`, slices, or safe predicates.
* For dicts: only use `d["key"]` if the key exists in both states, or use `"key" in d` / `d.get("key")`.
* For attributes: only use `obj.attr` if it exists in both states; otherwise, use `hasattr(obj, "attr")` or `getattr(obj, "attr", default)`.
* If a variable/attribute is present only in one state, any use of it must be guarded so that no exception is raised, and the final value still differs between states.

Input:
Function:
{code}

Line:
{line}

Existing expressions that already change value (one per line, may be empty):

State Differences:
{diff}

Complete Variable States before and after patch:
Before:
{before}

After:
{after}
"""
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
