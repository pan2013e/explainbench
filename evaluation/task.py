import json
from multiprocessing import Pool

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

from test_execution.test_runner import evaluate_test

__all__ = ['Task']

Schema = TypeVar('Schema', bound=BaseModel)

class Task(Generic[Schema]):
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

class Intent:
    class PBTAssertion(Task[schema.PBTAssertion]):
        QUESTION = (
            'For the provided test, what expression should go in [[MASKED 1]]?'
        )
        SCHEMA = schema.PBTAssertion

        @staticmethod
        def text_eval(pred: list[schema.PBTAssertion], gt: dict, **kwargs):
            '''
            Legacy syntax exact-match evaluation logic.
            '''
            import ast
            def _norm_code(snippet: str) -> str:
                try:
                    return ast.unparse(ast.parse(snippet))
                except SyntaxError:
                    return snippet # leave invalid Python code alone, wrong anyway
            return [_norm_code(p.assertion) == _norm_code(gt['answers'][0])
                    for p in pred]
        
        @staticmethod
        def _run_indiv_test(exec_idx, other_infos):
            indiv_pred, template_test, replace_answer, instance_id = other_infos
            predict_answer = indiv_pred.assertion
            predicted_test = template_test.replace(replace_answer, predict_answer)
            reproduce_result = evaluate_test(instance_id, predicted_test, exec_idx)
            return reproduce_result.reproduced

        @staticmethod
        def eval(pred: list[schema.PBTAssertion], gt: dict, **kwargs):
            instance_id = gt['instance_id']
            template_test = gt['test']
            replace_answer = gt['answers'][0]
            
            args = list(enumerate([
                (indiv_pred, template_test, replace_answer, instance_id)
                for indiv_pred in pred
            ]))
            p = Pool(len(pred))
            grades = p.starmap(
                Intent.PBTAssertion._run_indiv_test, args
            )
            return grades
        
        @classmethod
        def predict(cls, model: Model, explanation: str, **kwargs):
            import ast
            class RemoveExceptionMessages(ast.NodeTransformer):
                def visit_Module(self, node: ast.Module):
                    node.body = [
                        elem for elem in node.body
                        if not (isinstance(elem, ast.Import) or
                                isinstance(elem, ast.ImportFrom))
                    ]
                    return self.generic_visit(node)
                
                def visit_Raise(self, node: ast.Raise):
                    if node.exc and isinstance(node.exc, ast.Call) and node.exc.args:
                        node.exc.args = []
                    return self.generic_visit(node)

                def visit_Assert(self, node: ast.Assert):
                    if node.msg:
                        node.msg = None
                    return self.generic_visit(node)

            masked_test = ast.unparse(
                RemoveExceptionMessages().visit(ast.parse(kwargs["test"]))
            )
            for idx, answer in enumerate(kwargs["answers"]):
                masked_test = masked_test.replace(answer, f"[[MASKED {idx+1}]]")
            prompt = cls._build_prompt(explanation, masked_test=masked_test)
            return model.infer(prompt, cls.SCHEMA)

    class FunctionOutput(Task[schema.FunctionOutputs]):
        QUESTION = (
            'For the provided function and inputs, what are the **intended return values**, strictly according to the explanation? When answering this question, adhere to the following instructions:\n\n1. Return one value per input. Make sure the number matches.\n2. When the function should raise an exception according to the explanation, provide the type of exception that would be triggered.\n3. Do your best to predict what the output would look like when printed. For example, primitive values like integers would be printed as is, while complex objects can be predicted as e.g. <path.to.Object object at 0xdeadbeef>, or through their representation as apparent from the input.\n4. Do NOT explain what is intended in natural language, except when there is NO good way to describe the intended behavior.\n\nNow, provide a list with intended return values according to the instructions above, each corresponding to a provided input scenario.'
        )
        SCHEMA = schema.FunctionOutputs

        @staticmethod
        def eval(pred: list[schema.FunctionOutputs], gt: dict, **kwargs):
            answer_list = gt["answers"]
            got_all_correct = [
                all(pred_output == true_output
                    for pred_output, true_output in zip(pred_func_output.outputs, answer_list))
                for pred_func_output in pred
            ]
            return got_all_correct
    
        @classmethod
        def predict(cls, model: Model, explanation: str, **kwargs):
            method_signature = kwargs["signature"]
            example_inputs = kwargs["example_inputs"]
            example_input_str = "\n\n".join(
                f"Example {i+1}:\n{example_input}"
                for i, example_input in enumerate(example_inputs)
            )
            prompt = cls._build_prompt(
                explanation,
                method_signature = method_signature,
                example_inputs = example_input_str
            )
            return model.infer(prompt, cls.SCHEMA)