import ast

from pydantic import BaseModel, field_validator
from evaluation.inference import Model

class Expression(BaseModel):
    expr: str
    
    @field_validator('expr')
    def validate_expr(cls, v: str):
        tree = ast.parse(v, mode='eval')
        assert isinstance(tree, ast.Expression)
        return v
    
    def as_ast(self):
        return ast.parse(self.expr, mode='eval')

# TODO: Check the prompt quality and improve it if necessary.
# TODO: Check if the answer candidates are too diverse
TEMPLATE = (
    "An LLM is being asked a question about a patch in a Python repository: \"After the given line is executed, what is the value of <expr> before and after the patch?\" "
    "Your task is to design a valid Python expression <expr> that best fits the question. "
    "You will be given a Python function in the repository, a specific line in this function, and the state differences at this line before and after the patch. The expression you design should reflect such differences. Make sure the value of the expression are primitive types (i.e., None, int, float, str, bool) or collections (e.g., list, dict) of primitive types.\n\n"
    "Function:\n{code}\n\n"
    "Line:\n{line}\n\n"
    "State Differences:\n{diff}\n\n"
    "Complete Variable States before and after patch:\n"
    "Before:\n{before}\n"
    "After:\n{after}\n\n"
)

MODEL = Model("gemini/gemini-2.5-flash", n=5)

def main(code, line, diff, before, after):
    prompt = TEMPLATE.format(code=code, line=line, diff=diff, before=before, after=after)
    print(prompt)
    print("-----")
    response = MODEL.infer(prompt, Expression)
    print(response)
    input()
    return response

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
    before = "{'separable_matrix': {'py/object': 'numpy.ndarray', 'dtype': 'float64', 'values': [[1.0, 1.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0]]}"
    after = "{'separable_matrix': {'py/object': 'numpy.ndarray', 'dtype': 'float64', 'values': [[1.0, 1.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]}"
    main(code, line, before, after)
