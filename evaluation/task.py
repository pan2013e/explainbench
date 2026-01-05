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
    is_subpath,
    simple_name_eq,
    set_f1_score,
    mcq_score,
    params_eq,
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
        'Within the context of the provided function and inputs, immediately {before_or_after} the execution of the specified line, which of the following expressions have different values before and after the patch?\n\n'
        'Choices:\n'
        '{choices}\n\n'
        'Hints:\n'
        '1. `__return__` may be used in an expression to refer to the function\'s return value.\n'
        '2. `__exception__` may be used in an expression to refer to an exception caught in the function. It is a list of str with length 2. The first element is the exception type as str, and the second element is the exception message as str.\n'
        '3. The specified line may not be reached or executed due to an uncaught exception. For simplicity, you may treat raising such an exception as the function returning an `__exception__` object.\n'
        '4. Select one or more options. Please answer using only the option letter(s) (e.g., "a", "b").'
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
    
    @staticmethod
    def eval(pred: list[schema.Effect], gt: dict, **kwargs):
        answers = gt.get('answer', gt)
        return [mcq_score(p.answer, answers) for p in pred]

class Reachability(Task[schema.Effect]):
    QUESTION = (
        'Within the context of the provided function and inputs, which of the following lines are reachable during execution?'
        'Choices:\n'
        '{choices}\n\n'
        'Hints:\n'
        '1. The numeric range shown after each option corresponds to the line numbers in the original source code where that statement appears.'
        '2. It is possible that all lines are reachable. In this case, the range will always be [-1, -1]'
        '3. Select one or more options. Please answer using only the option letter(s) (e.g., "a", "b").'
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

    @staticmethod
    def eval(pred: list[schema.Effect], gt: dict, **kwargs):
        answers = gt.get('answer', gt)
        return [mcq_score(p.answer, answers) for p in pred]

if __name__ == "__main__":
    STEP2_PATH = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/step4.json"

    # Helpers
    def get_expl(agent, instance_id):
        from evaluation.util import load_explanation
        expl = load_explanation(agent)[instance_id]
        return expl[0] if expl else 'EMPTY'
    
    def get_function_input(metadata):
        import io
        output = io.StringIO()
        pre = metadata['buggy_function_param']
        post = metadata['patched_function_param']
        if params_eq(pre, post):
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

    def get_ctx_and_gt(data):
        question_type = data.get('question_type', 'expression changes')
        if question_type == 'expression changes':
            ctx = {
                'function_code_before_patch': data['function_code_before_patch'],
                'function_inputs': get_function_input(data),
                'line': data['location'],
                'choices': data['choices'],
                'before_or_after': data['before_or_after'],
            }
            task_cls = Effect
        elif question_type == 'reachability':
            ctx = {
                'function_code_before_patch': data['function_code_before_patch'],
                'function_inputs': get_function_input(data),
                'choices': data['choices'],
            }
            task_cls = Reachability
        else:
            raise ValueError(f'Unknown question_type: {question_type}')
        gt = {
            'answer': data['answer']
        }
        return ctx, gt, task_cls


    model = Model('gemini/gemini-2.5-flash', n=5)
    with open(STEP2_PATH, 'r') as f:
        step2_data = json.load(f)

    output = {}
    for agent in step2_data:
        output[agent] = {}

    def infer_instance(agent, instance_id, instance_data):
        explanation = get_expl(agent, instance_id)
        context, gt, task_cls = get_ctx_and_gt(instance_data)
        res = task_cls.predict(model, explanation, **context)
        return agent, instance_id, res, gt, task_cls

    max_workers = int(os.getenv("EFFECT_EVAL_MAX_WORKERS", "4"))
    futures = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for agent, instances in step2_data.items():
            for instance_id, instance_data in instances.items():
                if instance_data:
                    futures.append(
                        executor.submit(infer_instance, agent, instance_id, instance_data)
                    )

        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Evaluating instances",
            unit="inst",
        ):
            try:
                agent, instance_id, res, gt, task_cls = future.result()
                scores = task_cls.eval(res, gt)
            except Exception as e:
                # Log the error and continue processing other instances
                print(f"Error during evaluation of an instance: {e}")
                continue
            output[agent][instance_id] = {
                'all_pred': [p.answer for p in res],
                'individual_scores': scores,
                'average': sum(scores) / len(scores) if scores else 0.0,
            }
    out_dir = os.path.dirname(__file__)
    out_path = os.path.join(out_dir, 'effect_eval_output.json')
    with open(out_path, 'w') as f:
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

    metrics_path = os.path.join(out_dir, 'metric.json')
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f"Saved results to {out_path}")
    print(f"Saved metrics to {metrics_path}")
    print("Agent metrics:")
    print(json.dumps(metrics, indent=2))
