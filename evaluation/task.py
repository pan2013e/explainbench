import json

from functools import lru_cache
from typing import Generic, ClassVar, TypeVar
from pydantic import BaseModel

from evaluation import schema
from evaluation.inference import Model
from evaluation.util import (
    EvalTimeout,
    is_subpath,
    simple_name_eq,
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
    def is_context_agent_specific(cls) -> bool:
        return False
    
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
            'Which existing classes or functions were buggy?\n\n'
            'Please follow these formatting rules strictly:\n'
            '1. For methods: use `<simple_class_name>.<method_name>`.\n'
            '  - Example: Bar.foo\n'
            '2. For functions: use `<function_name>`.\n'
            '  - Example: my_function\n'
            '  - If the function is nested inside another function, use `<outer_function>.<inner_function>`.\n'
            '3. For classes: use `<simple_class_name>`.\n'
            '  - Only include classes if the bug affects the class itself (e.g., class variables, decorators), not methods within it.\n\n'
            'Additional rules:\n'
            '1. If the bug is outside any existing classes or functions (e.g., in the global scope), answer with an empty list.\n'
            '2. If you cannot infer from the explanation, answer with an empty list.\n'
            '3. Do not include classes or functions that were newly added in the patch.'
        )
        SCHEMA = schema.Region
        
        @staticmethod
        def eval(pred: list[schema.Region], gt: dict):
            pred = [set((r.identifier, r.type) for r in p.region) for p in pred]
            gt = set((t[0], t[1]) for t in gt['buggy_function_names'])
            return [set_f1_score(p, gt, simple_name_eq) for p in pred]

class Effect(Task[schema.Effect]):
    QUESTION = (
        'Given the function and inputs, after the given executed line, what is the value of the given variable?'
    )
    SCHEMA = schema.Effect
    
    @staticmethod
    def eval(pred: list[schema.Effect], gt: dict, **kwargs):
        ...

if __name__ == "__main__":
    t = Effect
    model = Model('gemini/gemini-2.5-flash', n=10)
    explanation = "I have successfully implemented a fix for the NDDataRef mask propagation issue in astropy v5.3. \n\n## Problem Summary\nThe issue occurred when performing arithmetic operations on NDDataRef objects with `handle_mask=np.bitwise_or` where one operand had a mask and the other didn't. This would cause a TypeError: \"unsupported operand type(s) for |: 'int' and 'NoneType'\" because the code tried to call bitwise operations on an integer mask and None.\n\n## Solution Implemented\nI modified the `_arithmetic_mask` method in `/workspace/astropy__astropy__5.2/astropy/nddata/mixins/ndarithmetic.py` (lines 525-533) to properly handle cases where one mask is None when using custom handle_mask functions.\n\nThe fix adds explicit checks to return the non-None mask when one operand lacks a mask, instead of attempting to call the handle_mask function with None:\n\n```python\n# If one of the masks is None, return the other one when using custom handle_mask\nif self.mask is None:\n    return deepcopy(operand.mask)\nelif operand.mask is None:\n    return deepcopy(self.mask)\nelse:\n    # Now lets calculate the resulting mask (operation enforces copy)\n    return handle_mask(self.mask, operand.mask, **kwds)\n```\n\n## Verification Results\n\u2705 All examples from the issue description now work correctly\n\u2705 All 179 existing arithmetic tests continue to pass  \n\u2705 Backward compatibility is fully maintained\n\u2705 Edge cases with different handle_mask options work properly\n\u2705 The expected behavior is achieved: when one operand has no mask, the existing mask is copied over\n\nThe fix is minimal, focused, and addresses the exact issue while preserving all existing functionality."
    context = {
        'function_code': '''    def _arithmetic(
        self,
        operation,
        operand,
        propagate_uncertainties=True,
        handle_mask=np.logical_or,
        handle_meta=None,
        uncertainty_correlation=0,
        compare_wcs="first_found",
        operation_ignores_mask=False,
        axis=None,
        **kwds,
    ):
        kwds2 = {"mask": {}, "meta": {}, "wcs": {}, "data": {}, "uncertainty": {}}
        for i in kwds:
            splitted = i.split("_", 1)
            try:
                kwds2[splitted[0]][splitted[1]] = kwds[i]
            except KeyError:
                raise KeyError(f"Unknown prefix {splitted[0]} for parameter {i}")

        kwargs = {}

        if compare_wcs is None:
            kwargs["wcs"] = None
        elif compare_wcs in ["ff", "first_found"]:
            if self.wcs is None and hasattr(operand, "wcs"):
                kwargs["wcs"] = deepcopy(operand.wcs)
            else:
                kwargs["wcs"] = deepcopy(self.wcs)
        else:
            kwargs["wcs"] = self._arithmetic_wcs(
                operation, operand, compare_wcs, **kwds2["wcs"]
            )

        use_masked_arith = operand is None and self.mask is not None
        if use_masked_arith:
            if not operation_ignores_mask:
                if self.unit is not None and not hasattr(self.data, "unit"):
                    masked_input = Masked(self.data << self.unit, mask=self.mask)
                else:
                    masked_input = Masked(self.data, mask=self.mask)
            else:
                masked_input = np.ma.masked_array(self.data, self.mask)
            result = operation(masked_input, axis=axis)
            if not hasattr(result, "mask"):
                result = np.ma.masked_array(
                    result, mask=np.zeros_like(result, dtype=bool)
                )
        else:
            result = self._arithmetic_data(
                operation, operand, axis=axis, **kwds2["data"]
            )

        if not hasattr(result, "unit") and hasattr(self, "unit"):
            kwargs["unit"] = self.unit

        if propagate_uncertainties is None:
            kwargs["uncertainty"] = None
        elif not propagate_uncertainties:
            if self.uncertainty is None:
                kwargs["uncertainty"] = deepcopy(operand.uncertainty)
            else:
                kwargs["uncertainty"] = deepcopy(self.uncertainty)
        else:
            kwargs["uncertainty"] = self._arithmetic_uncertainty(
                operation,
                operand,
                result,
                uncertainty_correlation,
                axis=axis,
                **kwds2["uncertainty"],
            )

        if self.psf is not None or (operand is not None and operand.psf is not None):
            warnings.warn(
                f"Not setting psf attribute during {operation.__name__}.",
                AstropyUserWarning,
            )

        if handle_mask is None:
            pass
        elif hasattr(result, "mask"):
            kwargs["mask"] = None
        elif handle_mask in ["ff", "first_found"]:
            if self.mask is None:
                kwargs["mask"] = deepcopy(operand.mask)
            else:
                kwargs["mask"] = deepcopy(self.mask)
        else:
            kwargs["mask"] = self._arithmetic_mask(
                operation, operand, handle_mask, axis=axis, **kwds2["mask"]
            )

        if handle_meta is None:
            kwargs["meta"] = None
        elif handle_meta in ["ff", "first_found"]:
            if not self.meta:
                kwargs["meta"] = deepcopy(operand.meta)
            else:
                kwargs["meta"] = deepcopy(self.meta)
        else:
            kwargs["meta"] = self._arithmetic_meta(
                operation, operand, handle_meta, **kwds2["meta"]
            )

        return result, kwargs''',
        'function_input': '''{'self': {'_data': {'dtype': 'int64', 'values': [[0, 1, 0], [1, 0, 1], [0, 1, 0]]}, '_mask': {'dtype': 'int64', 'values': [[0, 1, 64], [8, 0, 1], [2, 1, 0]]}, '_wcs': None, '_meta': {}, '_unit': None, '_uncertainty': None, '_psf': None}, 'operation': '<non-serializable: UserWarning>', 'operand': {'_data': {'dtype': 'float64', 'values': 1.0}, '_mask': None, '_wcs': None, '_meta': {}, '_unit': None, '_uncertainty': None, '_psf': None}, 'propagate_uncertainties': True, 'handle_mask': '<non-serializable: UserWarning>', 'handle_meta': None, 'uncertainty_correlation': 0, 'compare_wcs': 'first_found', 'operation_ignores_mask': False, 'axis': None, '**kwds': {}}''',
        'executed_line': 'kwargs["mask"] = self._arithmetic_mask(',
        'variable_in_question': 'kwargs["mask"]',
    }
    prompt = t._build_prompt(explanation, **context)
    print(prompt)
    res = t.predict(model, explanation, **context)
    print(res)