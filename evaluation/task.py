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

__all__ = [
    'NAME_TASK_MAP',
    'TASK_NAME_MAP',
    'RootCause',
]

Schema = TypeVar('Schema', bound=BaseModel)

class Task(Generic[Schema], metaclass=EvalTimeout):
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

    class Line(Task[schema.Line]):
        QUESTION = (
            'Which lines were buggy? '
            'You can either answer with line numbers or line contents. '
            'Please exclude any test code or docstrings.'
        )
        SCHEMA = schema.Line
        
        @staticmethod
        def eval(pred: list[schema.Line], gt: dict):
            pred_sets = []
            for p in pred:
                pred_set = set()
                for line in p.line:
                    if isinstance(line, schema.LineRange):
                        pred_set.update((line.file, n) for n in range(line.start, line.end + 1))
                    elif isinstance(line, schema.LineContent):
                        pred_set.add((line.file, line.content))
                pred_sets.append(pred_set)
            gt_set = set()
            for line_info, content_info in zip(gt['buggy_line_numbers'], gt['buggy_line_contents'], strict=True):
                assert line_info[0] == content_info[0]
                for lineno, content in zip(line_info[1], content_info[1], strict=True):
                    gt_set.add((line_info[0], lineno, content))
            return [set_f1_score(p, gt_set, is_line_equal) for p in pred_sets]

NAME_TASK_MAP = {
    'rootcause.file': RootCause.File,
    'rootcause.region': RootCause.Region,
    'rootcause.line': RootCause.Line,
}
TASK_NAME_MAP = {v: k for k, v in NAME_TASK_MAP.items()}