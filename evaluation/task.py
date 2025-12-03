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
    CTX_AGENT_SPECIFIC: ClassVar[bool] = False
    
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
        'Given the function and inputs, {before_or_after} the given line is executed, what are the values of the given expression before and after the patch?\n\n'
        'Notes:\n'
        '1. For the values, answer with strings that can be directly parsed by Python\'s eval() function.\n'
        '2. It is possible that an exception is raised before or at the given line, so the value may not exist. In this case, please answer with the type and message of the exception.\n'
        '3. If you cannot infer from the explanation, please answer with an empty string.'
    )
    SCHEMA = schema.Effect
    CTX_AGENT_SPECIFIC = True
    
    @classmethod
    def _build_prompt(cls, explanation, **kwargs):
        before_or_after = kwargs.pop('before_or_after', 'before')
        return cls.TEMPLATE.format(schema=cls._schema_string(), explanation=explanation, question=cls.QUESTION.format(before_or_after=before_or_after), context=cls._build_context(**kwargs))
    
    @staticmethod
    def eval(pred: list[schema.Effect], gt: dict, **kwargs):
        def eval_single(pred: schema.Effect, gt):
            score = 0
            if pred.before == gt['buggy_value']:
                score += 0.5
            if pred.after == gt['patched_value']:
                score += 0.5
            return score
        return [eval_single(p, gt) for p in pred]

if __name__ == "__main__":
    # Helpers
    def get_expl(agent, instance_id):
        from evaluation.util import load_explanation
        expl = load_explanation(agent)[instance_id]
        return expl[0] if expl else 'EMPTY'
    
    def get_simple_function_name(metadata):
        name = metadata['function_name']
        if ":" in name:
            name = name.split(":")[-1]
        if "." in name:
            name = name.split(".")[-1]
        return name
    
    def get_function_input(metadata):
        import io
        from tracer.serializer import deserialize
        output = io.StringIO()
        pre = metadata['buggy_function_param']
        post = metadata['patched_function_param']
        if pre == post:
            print(pre, file=output)
        else:
            print("\n# Before Patch:\n", file=output)
            print(pre, file=output)
            print("\n# After Patch:\n", file=output)
            print(post, file=output)
            print("\n", file=output)
        contents = output.getvalue()
        output.close()
        return contents

    def get_ctx_and_gt(agent, instance_id):
        import os
        from dataset.extract_ground_truths.effect.source_util import get_function_code
        DIR = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(DIR, "../dataset/extract_ground_truths/effect/tmp/step1.json"), 'r') as f:
            data = json.load(f)[agent][instance_id]
        
        ctx = {
            'function_code_before_patch': 
                get_function_code(
                    instance_id,
                    data['file_path'],
                    get_simple_function_name(data),
                    line_hint=(data['buggy_lineno'], None),
                    remove_doc=True,
                )[0],
            'function_input': get_function_input(data),
            'line': data['statement'],
        }
        gt = {}
        return ctx, gt
    
    # Example
    model = Model('gemini/gemini-2.5-flash', n=5)
    agent = '20250805_openhands-Qwen3-Coder-480B-A35B-Instruct'
    instance_id = 'astropy__astropy-13579'
    explanation = get_expl(agent, instance_id)
    if explanation == 'EMPTY':
        print('null')
        exit(0)
    context, gt = get_ctx_and_gt(agent, instance_id)
    # predict actually calls _build_prompt internally
    # here we call again just to display the full prompt
    prompt = Effect._build_prompt(explanation, **context)
    print(prompt)
    res = Effect.predict(model, explanation, **context)
    print(res)