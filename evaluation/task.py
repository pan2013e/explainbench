import json

from functools import lru_cache
from typing import Generic, ClassVar, TypeVar
from pydantic import BaseModel

from evaluation import schema
from evaluation.inference import Model
from evaluation.util import (
    is_subpath,
    set_f1_score,
)

__all__ = [
    'NAME_TASK_MAP',
    'TASK_NAME_MAP',
    'RootCause',
]

Schema = TypeVar('Schema', bound=BaseModel)

class Task(Generic[Schema]):
    TEMPLATE: ClassVar[str] = (
        "An AI agent fixed a bug in a code repository and provided an explanation for the patch. "
        "You will be given this patch explanation, and your task is to answer questions about the bug and patch described by the explanation. "
        "You should respond in JSON format, complying with the following Pydantic schema: {schema}\n\n"
        "Patch Explanation:\n{explanation}\n\n"
        "Question:\n{question}\n"
    )
    QUESTION: ClassVar[str]
    SCHEMA: ClassVar[type[Schema]]

    @classmethod
    @lru_cache
    def _schema_string(cls):
        return json.dumps(cls.SCHEMA.model_json_schema(mode='serialization'))
    
    @classmethod
    def _build_prompt(cls, explanation: str):
        return cls.TEMPLATE.format(schema=cls._schema_string(), explanation=explanation, question=cls.QUESTION)
    
    @classmethod
    def predict(cls, model: Model, explanation: str):
        prompt = cls._build_prompt(explanation)
        return model.infer(prompt, cls.SCHEMA)
    
    @staticmethod
    def eval(pred, gt, **kwargs) -> list:
        raise NotImplementedError()

class RootCause:
    class File(Task[schema.File]):
        QUESTION = 'Which files were buggy?'
        SCHEMA = schema.File

        @staticmethod
        def eval(pred: list[schema.File], gt: dict):
            pred = [set(p.file) for p in pred]
            gt = set(gt['buggy_file_names'])
            return [set_f1_score(p, gt, is_subpath) for p in pred]

    class Region(Task[schema.Region]):
        QUESTION = 'Which classes or functions were buggy? If not applicable, please respond with an empty list.'
        SCHEMA = schema.Region
        
        @staticmethod
        def eval(pred: schema.Region, gt: dict):
            ...

    class Line(Task[schema.Line]):
        QUESTION = 'Which lines were buggy?'
        SCHEMA = schema.Line
        
        @staticmethod
        def eval(pred, gt):
            ...

NAME_TASK_MAP = {
    'rootcause.file': RootCause.File,
    'rootcause.region': RootCause.Region,
    'rootcause.line': RootCause.Line,
}
TASK_NAME_MAP = {v: k for k, v in NAME_TASK_MAP.items()}