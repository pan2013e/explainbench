import json

from functools import lru_cache
from typing import Generic, ClassVar, TypeVar
from pydantic import BaseModel

from evaluation import schema
from evaluation.inference import Model
from evaluation.util import (
    EvalTimeout,
    mcq_score,
    format_mcq_choices,
)

__all__ = ['Task']

Schema = TypeVar('Schema', bound=BaseModel)

class Task(Generic[Schema], metaclass=EvalTimeout):
    TEMPLATE: ClassVar[str] = (
        "An AI agent fixed a bug in a code repository and provided an explanation for the patch. "
        "You will be given this patch explanation, and your task is to answer questions about the bug and patch described by the explanation. "
        "Your answer must be grounded only in the provided explanation; do not use outside knowledge or assumptions. "
        "You should respond in JSON format, complying with the following Pydantic schema: {schema}\n\n"
        "Patch Explanation:\n*** Explanation Start ***\n{explanation}\n*** Explanation End ***\n\n"
        "{context}"
        "Question:\n{question}\n"
    )
    QUESTION: ClassVar[str]
    SCHEMA: ClassVar[type[Schema]]
    CTX_AGENT_SPECIFIC: ClassVar[bool] = False
    
    _registry = {} # type: dict[str, type[Task]]
    
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls_id = cls.__qualname__.lower()
        if not cls_id.startswith('_'):
            cls._registry[cls_id] = cls

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
        if cls.QUESTION == "UNDEFINED":
            raise NotImplementedError(f"Should use a subclass of {cls.__qualname__} with a specific QUESTION.")
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
    
    @classmethod
    def eval(cls, pred: list, gt: dict, **kwargs) -> list[float]:
        raise NotImplementedError()

class _MCQ(Task[schema.MCQ]):
    QUESTION = "UNDEFINED"
    SCHEMA = schema.MCQ
    
    @classmethod
    def eval(cls, pred: list[schema.MCQ], gt: dict, **kwargs):
        answers = gt.get('answer', gt)
        return [mcq_score(p.answer, answers) for p in pred]

class Local:
    class Effect(_MCQ):
        QUESTION = (
            'Within the context of the provided function and inputs, immediately {before_or_after} the execution of the specified line, which of the following expressions have different values before and after the patch?\n\n'
            'Choices:\n'
            '{choices}\n\n'
            'Hints:\n'
            '1. `__return__` may be used in an expression to refer to the function\'s return value.\n'
            '2. `__exception__` may be used in an expression to refer to an exception caught in the function. It is a list of str with length 2. The first element is the exception type as str, and the second element is the exception message as str.\n'
            '3. The specified line may not be reached or completely executed due to an uncaught exception. For simplicity, you may treat raising such an exception as the function returning an `__exception__` object.\n'
            '4. Select one or more options. Please answer using only the option letter(s) (e.g., "a", "b"). For multiple selections, answer like: {{"answer": ["a", "b"]}}'
        )
        CTX_AGENT_SPECIFIC = True
        
        @classmethod
        def _build_prompt(cls, explanation, **kwargs):
            before_or_after = kwargs.pop('before_or_after', 'before')
            choices = kwargs.pop('choices')
            return cls.TEMPLATE.format(schema=cls._schema_string(), explanation=explanation, question=cls.QUESTION.format(before_or_after=before_or_after, choices=format_mcq_choices(choices)), context=cls._build_context(**kwargs))

    class Intent(Effect):
        QUESTION = (
            'Within the context of the provided function and inputs, immediately {before_or_after} the execution of the specified line, which of the following expressions best describe what the developer-intended change is?\n\n'
            'Choices:\n'
            '{choices}\n\n'
            'Hints:\n'
            '1. `__return__` may be used in an expression to refer to the function\'s return value.\n'
            '2. `__exception__` may be used in an expression to refer to an exception caught in the function. It is a list of str with length 2. The first element is the exception type as str, and the second element is the exception message as str.\n'
            '3. The specified line may not be reached or completely executed due to an uncaught exception. For simplicity, you may treat raising such an exception as the function returning an `__exception__` object.\n'
            '4. Select one or more options. Please answer using only the option letter(s) (e.g., "a", "b"). For multiple selections, answer like: {{"answer": ["a", "b"]}}'
        )
        CTX_AGENT_SPECIFIC = False
