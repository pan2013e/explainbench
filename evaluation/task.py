import json

from functools import lru_cache
from typing import Generic, ClassVar, TypeVar
from pydantic import BaseModel

from evaluation import schema
from evaluation.inference import Model
from evaluation.util import (
    EvalTimeout,
    is_subpath,
    set_f1_score,
)

__all__ = ['Task']

Schema = TypeVar('Schema', bound=BaseModel)

class Task(Generic[Schema], metaclass=EvalTimeout):
    TEMPLATE: ClassVar[str] = (
        "An AI agent fixed a bug in a code repository and provided an explanation for the patch. "
        "You will be given this patch explanation, and your task is to answer questions about the bug and patch described by the explanation. "
        "You should respond in JSON format, complying with the following Pydantic schema: {schema}\n\n"
        "Patch Explanation:\n{explanation}\n\n"
        "{context}"
        "Question:\n{question}\n"
    )
    QUESTION: ClassVar[str]
    SCHEMA: ClassVar[type[Schema]]
    
    _registry = {} # type: dict[str, type[Task]]
    
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._registry[cls.__qualname__.lower()] = cls

    @classmethod
    @lru_cache
    def _schema_string(cls):
        return json.dumps(cls.SCHEMA.model_json_schema(mode='serialization'))
    
    @classmethod
    def _build_context(cls, **kwargs):
        if not kwargs:
            return ''
        key_formatter = lambda key: ' '.join([word.capitalize() for word in key.split('_')])
        return '\n\n'.join(f'{key_formatter(k)}:\n{v}' for k, v in kwargs.items()) + '\n\n'
    
    @classmethod
    def _build_prompt(cls, explanation: str, **kwargs):
        return cls.TEMPLATE.format(schema=cls._schema_string(), explanation=explanation, question=cls.QUESTION, context=cls._build_context(**kwargs))

    @classmethod
    def repr(cls):
        return cls.__qualname__.lower().replace('.', '_')
    
    @classmethod
    def get_task(cls, name: str):
        name = name.lower()
        if name not in cls._registry:
            raise ValueError(f'Unknown task name: {name}, available tasks: {list(cls._registry.keys())}')
        return cls._registry[name]

    @classmethod
    def predict(cls, model: Model, explanation: str, **kwargs):
        prompt = cls._build_prompt(explanation, **kwargs)
        return model.infer(prompt, cls.SCHEMA)
    
    @staticmethod
    def eval(pred: list, gt: dict, **kwargs) -> list[float]:
        raise NotImplementedError()

class RootCause:
    class File(Task[schema.File]):
        QUESTION = (
            'Which files were buggy? '
            'Please answer with the file paths, and exclude any test files or doc files from your response. '
            'If you cannot infer from the explanation, please answer with an empty list.'
        )
        SCHEMA = schema.File

        @staticmethod
        def eval(pred: list[schema.File], gt: dict):
            pred = [set(p.file) for p in pred]
            gt = set(gt['buggy_file_names'])
            return [set_f1_score(p, gt, is_subpath) for p in pred]

    class Region(Task[schema.Region]):
        QUESTION = (
            'Which existing classes or functions were buggy? '
            'Please answer with simple identifier names (without higher-level namespaces) and their types (class or function). '
            'If you cannot infer from the explanation, please answer with an empty list. '
            'You don\'t need to consider newly added classes or functions.' 
        )
        SCHEMA = schema.Region
        
        @staticmethod
        def eval(pred: list[schema.Region], gt: dict):
            def postprocess(qualified_name: str):
                qualified_name = qualified_name.strip()
                if qualified_name.endswith('()'):
                    qualified_name = qualified_name[:-2]
                return qualified_name.split('.')[-1]
            pred = [set((postprocess(r.identifier), r.type) for r in p.region) for p in pred]
            gt = set((t[0], t[1]) for t in gt['buggy_function_names'])
            return [set_f1_score(p, gt) for p in pred]

class Effect:
    class Variable(Task[schema.Variable]):
        QUESTION = (
            'Given the function and inputs, after the given executed line, what is the value of the given variable?'
        )
        SCHEMA = schema.Variable
        
        @staticmethod
        def eval(pred: list[schema.Variable], gt: dict, **kwargs):
            ...

if __name__ == "__main__":
    t = Effect.Variable
    model = Model('gemini/gemini-2.5-flash', n=10)
    # explanation = "EMPTY"
    explanation = "Now let me summarize what I've accomplished:\n\n## Summary\n\nI successfully fixed the bug in the `separability_matrix` function for nested CompoundModels. \n\n### Problem\nThe issue was that `separability_matrix(m.Pix2Sky_TAN() & cm)` where `cm = m.Linear1D(10) & m.Linear1D(5)` was incorrectly showing coupled inputs/outputs for the Linear1D models:\n\n**Before fix:**\n```\n[[ True  True False False]\n [ True  True False False]\n [False False  True  True]   # Wrong: should be [False False  True False]\n [False False  True  True]]  # Wrong: should be [False False False  True]\n```\n\n**After fix:**\n```\n[[ True  True False False]\n [ True  True False False]\n [False False  True False]   # Correct\n [False False False  True]]  # Correct\n```\n\n### Root Cause\nThe bug was in the `_cstack` function in `astropy/modeling/separable.py` at line 245. When handling the `&` (concatenation) operator with a right operand that was already a computed matrix (from a nested CompoundModel), the code was overwriting the matrix values with all 1s instead of preserving the separability structure.\n\n### Fix\nI changed line 245 from:\n```python\ncright[-right.shape[0]:, -right.shape[1]:] = 1\n```\nto:\n```python\ncright[-right.shape[0]:, -right.shape[1]:] = right\n```\n\nThis preserves the separability information from nested CompoundModels instead of overwriting it.\n\n### Verification\n1. \u2705 Original reproduce script now shows correct behavior\n2. \u2705 All existing separability tests pass\n3. \u2705 Additional edge cases tested and pass\n4. \u2705 No regressions in the broader modeling test suite (unrelated numpy deprecation warnings don't affect functionality)\n\nThe fix is minimal, targeted, and resolves the specific issue while maintaining backward compatibility."
    patch = '''diff --git a/astropy/modeling/separable.py b/astropy/modeling/separable.py
--- a/astropy/modeling/separable.py
+++ b/astropy/modeling/separable.py
@@ -242,7 +242,7 @@ def _cstack(left, right):
         cright = _coord_matrix(right, 'right', noutp)
     else:
         cright = np.zeros((noutp, right.shape[1]))
-        cright[-right.shape[0]:, -right.shape[1]:] = 1
+        cright[-right.shape[0]:, -right.shape[1]:] = right
 
     return np.hstack([cleft, cright])
 
'''
    context = {
        'patch': patch,
        'function_code': '''def _cstack(left, right):
    noutp = _compute_n_outputs(left, right)
    if isinstance(left, Model):
        cleft = _coord_matrix(left, 'left', noutp)
    else:
        cleft = np.zeros((noutp, left.shape[1]))
        cleft[: left.shape[0], : left.shape[1]] = left
    if isinstance(right, Model):
        cright = _coord_matrix(right, 'right', noutp)
    else:
        cright = np.zeros((noutp, right.shape[1]))
        cright[-right.shape[0]:, -right.shape[1]:] = right

    return np.hstack([cleft, cright])''',
        'function_input': '''{'left': array([[1., 1., 0.],
       [1., 1., 0.],
       [0., 0., 1.]]), 'right': array([[1., 0.],
       [0., 1.]])}''',
        'executed_line': 'cright[-right.shape[0]:, -right.shape[1]:] = right',
        'variable_in_question': 'cright'
    }
    prompt = t._build_prompt(explanation, **context)
    print(prompt)
    res = t.predict(model, explanation, **context)
    print(res)