import json

from functools import lru_cache
from typing import Generic, ClassVar, TypeVar
from pydantic import BaseModel

from evaluation import schema
from evaluation.inference import Model
from evaluation.util import (
    EvalTimeout,
    is_subpath,
    is_line_equal,
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
            'Which classes or functions were buggy? '
            'If a method of a class is buggy, you only need to answer with the method name. '
            'If not applicable or you cannot infer from the explanation, please answer with an empty list.'
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
