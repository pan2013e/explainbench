from typing import Generic, ClassVar, TypeVar
from pydantic import BaseModel

from evaluation import schema
from evaluation.inference import Model

__all__ = [
    'RootCause',
]

Schema = TypeVar('Schema', bound=BaseModel)

class Task(Generic[Schema]):
    TEMPLATE: ClassVar[str] = (
        "An AI agent fixed a bug in a code repository and provided an explanation for the patch. "
        "You will be given this patch explanation, and your task is to answer questions about the bug and patch described by the explanation. "
        "You should respond in JSON format.\n\n"
        "Patch Explanation:\n{explanation}\n\n"
        "Question:\n{question}\n"
    )
    QUESTION: ClassVar[str]
    SCHEMA: ClassVar[type[Schema]]
    
    @classmethod
    def build_prompt(cls, explanation: str):
        return cls.TEMPLATE.format(explanation=explanation, question=cls.QUESTION)
    
    @classmethod
    def predict(cls, model: Model, explanation: str):
        prompt = cls.build_prompt(explanation)
        return model.infer(prompt, cls.SCHEMA)

class RootCause:
    class File(Task[schema.File]):
        QUESTION = 'Which files were buggy?'
        SCHEMA = schema.File
    
    class Function(Task[schema.Function]):
        QUESTION = 'Which classes or functions were buggy?'
        SCHEMA = schema.Function

    class Line(Task[schema.Line]):
        QUESTION = 'Which lines were buggy?'
        SCHEMA = schema.Line
