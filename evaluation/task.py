import os
import json

from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Generic, ClassVar, TypeVar
from pydantic import BaseModel
from tqdm.auto import tqdm

from evaluation import schema
from evaluation.inference import Model
from evaluation.util import (
    EvalTimeout,
    mcq_score,
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

class _ExpressionChanges(Task[schema.Effect]):
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
    SCHEMA = schema.Effect
    CTX_AGENT_SPECIFIC = True
    
    @staticmethod
    def _format_choices(exprs: list[str], formatter='{})'):
        assert len(exprs) <= 26, 'Too many choices to label with single letters'
        labels = 'abcdefghijklmnopqrstuvwxyz'
        return '\n'.join(f'{formatter.format(labels[i])} {expr}' for i, expr in enumerate(exprs))
    
    @classmethod
    def _build_prompt(cls, explanation, **kwargs):
        before_or_after = kwargs.pop('before_or_after', 'before')
        choices = kwargs.pop('choices')
        return cls.TEMPLATE.format(schema=cls._schema_string(), explanation=explanation, question=cls.QUESTION.format(before_or_after=before_or_after, choices=cls._format_choices(choices)), context=cls._build_context(**kwargs))

class _Reachability(Task[schema.Effect]):
    QUESTION = (
        'Within the context of the provided function and inputs, which of the following lines exhibit a change in reachability before and after the patch?'
        'Choices:\n'
        '{choices}\n\n'
        'Hints:\n'
        '1. The numeric range shown after each option corresponds to the line numbers in the original source code where that statement appears.'
        '2. Select one or more options. Please answer using only the option letter(s) (e.g., "a", "b"). For multiple selections, answer like: {{"answer": ["a", "b"]}}'
    )
    SCHEMA = schema.Effect
    CTX_AGENT_SPECIFIC = True

    @staticmethod
    def _format_choices(choices: list):
        assert len(choices) <= 26, 'Too many choices to label with single letters'
        labels = 'abcdefghijklmnopqrstuvwxyz'
        formatted = []
        for i, choice in enumerate(choices):
            code, lines = choice
            code_str = str(code).strip()
            if code_str == "None of the above":
                formatted.append(f'{labels[i]}) {code_str}')
            else:
                line_start, line_end = lines
                formatted.append(f'{labels[i]}) {code_str} [{line_start}, {line_end}]')
        return '\n'.join(formatted)

    @classmethod
    def _build_prompt(cls, explanation, **kwargs):
        choices = kwargs.pop('choices')
        return cls.TEMPLATE.format(
            schema=cls._schema_string(),
            explanation=explanation,
            question=cls.QUESTION.format(choices=cls._format_choices(choices)),
            context=cls._build_context(**kwargs),
        )

class Effect(Task[schema.Effect]):
    QUESTION = "DUMMY"
    SCHEMA = schema.Effect
    
    @classmethod
    def predict(cls, model, explanation, **kwargs):
        qt = kwargs.pop('question_type')
        if qt == 'expression changes':
            ctx_keys = ['function_code_before_patch', 'function_parameters_before_patch', 'line', 'choices', 'before_or_after']
            context = {k: kwargs[k] for k in ctx_keys}
            return _ExpressionChanges.predict(model, explanation, **context)
        elif qt == 'reachability':
            ctx_keys = ['function_code_before_patch', 'function_parameters_before_patch', 'choices']
            context = {k: kwargs[k] for k in ctx_keys}
            return _Reachability.predict(model, explanation, **context)
        else:
            raise ValueError(f'Unknown question_type: {qt}')

    @staticmethod
    def eval(pred: list[schema.Effect], gt: dict, **kwargs):
        answers = gt.get('answer', gt)
        return [mcq_score(p.answer, answers) for p in pred]

if __name__ == "__main__":
    STEP4_PATH = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/results/step4.json"
    OUTPUT_FILE_INDIVIDUAL = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/results/eval.individual.effect.json"
    OUTPUT_FILE_ALL = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/results/eval.all.effect.json"

    # Helpers
    def get_expl(agent, instance_id):
        from evaluation.util import load_explanation
        if agent == 'blank':
            return 'EMPTY'
        expl = load_explanation(agent)[instance_id]
        return expl[0] if expl else 'EMPTY'
    
    def get_function_input(metadata):
        import io
        output = io.StringIO()
        pre = metadata['buggy_function_param']
        print(pre, file=output)
        contents = output.getvalue()
        output.close()
        if len(contents) > 20000:
            contents = contents[:20000] + " ...(truncated)"
        return contents

    def get_ctx_and_gt(data):
        ctx = {
            'question_type': data['question_type'],
            'function_code_before_patch': data['function_code_before_patch'],
            'function_parameters_before_patch': get_function_input(data),
            'line': data['location'],
            'choices': data['choices'],
            'before_or_after': data['before_or_after'],
        }
        gt = {
            'answer': data['answer']
        }
        return ctx, gt

    model = Model('gpt-5-mini-2025-08-07', n=5)
    with open(STEP4_PATH, 'r') as f:
        step4_data = json.load(f)

    output = {}
    for agent in step4_data:
        output[agent] = {}

    def infer_instance(agent, instance_id, instance_data):
        explanation = get_expl(agent, instance_id)
        context, gt = get_ctx_and_gt(instance_data)
        res = Effect.predict(model, explanation, **context)
        return agent, instance_id, res, gt

    max_workers = 40
    futures = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for agent, instances in step4_data.items():
            if agent not in ("20250805_openhands-Qwen3-Coder-480B-A35B-Instruct", "20250807_mini-v1.7.0_gpt-5-mini"):
                for instance_id, instance_data in instances.items():
                    if instance_data:
                        futures.append(
                            executor.submit(infer_instance, agent, instance_id, instance_data)
                        )
        pbar = tqdm(
            as_completed(futures),
            total=len(futures),
        )
        for future in pbar:
            pbar.set_postfix(**model.tqdm_usage())
            try:
                agent, instance_id, res, gt = future.result()
                scores = Effect.eval(res, gt)
            except Exception as e:
                # Log the error and continue processing other instances
                print(f"Error during evaluation of an instance: {type(e).__name__}: {e}")
                continue
            output[agent][instance_id] = {
                'all_pred': [p.answer for p in res],
                'individual_scores': scores,
                'average': sum(scores) / len(scores) if scores else 0.0,
            }
    with open(OUTPUT_FILE_INDIVIDUAL, 'w') as f:
        json.dump(output, f, indent=2)

    # Compute per-agent metrics
    metrics = {}
    for agent, instances in output.items():
        best_scores = []
        mean_scores = []
        for instance in instances.values():
            scores = instance.get('individual_scores') or []
            if not scores:
                continue
            best_scores.append(max(scores))
            mean_scores.append(instance.get('average', 0.0))
        if best_scores:
            best_per_instance_mean = sum(best_scores) / len(best_scores)
        else:
            best_per_instance_mean = 0.0
        if mean_scores:
            mean_of_instance_means = sum(mean_scores) / len(mean_scores)
        else:
            mean_of_instance_means = 0.0
        metrics[agent] = {
            'best_per_instance_mean': best_per_instance_mean,
            'mean_of_instance_means': mean_of_instance_means,
        }

    with open(OUTPUT_FILE_ALL, 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f"Saved results to {OUTPUT_FILE_INDIVIDUAL}")
    print(f"Saved metrics to {OUTPUT_FILE_ALL}")
    print("Agent metrics:")
    print(json.dumps(metrics, indent=2))
