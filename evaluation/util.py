import os
import json
import signal
import inspect
import warnings
import numpy as np

from functools import wraps
from typing import Callable

DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(DIR, '..', 'dataset')

def mcq_score(pred: list[str], gt: list[str]):
    assert len(gt) > 0
    pred_set = set(pred)
    gt_set = set(gt)
    if pred_set - gt_set:
        return 0.0
    return len(pred_set & gt_set) / len(gt_set)

def format_mcq_choices(exprs: list[str], formatter='{})'):
    assert len(exprs) <= 26, 'Too many choices to label with single letters'
    labels = 'abcdefghijklmnopqrstuvwxyz'
    return '\n'.join(f'{formatter.format(labels[i])} {expr}' for i, expr in enumerate(exprs))

def load_explanation(split: str) -> dict[str, list[str]]:
    with open(os.path.join(DATASET_DIR, 'explanations', 'dataset.json')) as f:
        data = json.load(f)[split]
    return data

def load_ground_truth() -> list[dict]:
    with open(os.path.join(DATASET_DIR, 'extract_ground_truths', 'localization', 'ground_truth.jsonl')) as f:
        data = [json.loads(line) for line in f]
    return data

def load_context(task, agent_id=None) -> list[dict]:
    if not task.CTX_AGENT_SPECIFIC:
        path = os.path.join(DATASET_DIR, f'context/{task.repr()}.json')
        if not os.path.exists(path):
            return None
    else:
        assert agent_id is not None, "agent_id must be provided for agent-specific context"
        path = os.path.join(DATASET_DIR, f'context/{task.repr()}__{agent_id}.json')
        if not os.path.exists(path):
            raise ValueError(f"Context file not found for agent-specific context: {path}")
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list) and all(isinstance(item, dict) for item in data)
    return data

def result_statistics(data: dict[str, list]):
    n_runs = list(zip(*data.values(), strict=True))
    n_runs = [np.mean(run) for run in n_runs]
    return {
        'metric_values': n_runs,
        'mean': np.mean(n_runs),
        'std': np.std(n_runs),
        'max': np.max(n_runs),
        'min': np.min(n_runs),
    }

def timeout(seconds=30):
    def decorator(func: Callable[[list, dict], list[float]]):
        @wraps(func)
        def wrapper(*args, **kwargs):
            def handler(signum, frame):
                warnings.warn(f'{func.__qualname__} timed out after {seconds} seconds. Setting result to zeros.')
                raise TimeoutError()
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(seconds)
            try:
                result = func(*args, **kwargs)
            except TimeoutError:
                bound = inspect.signature(func).bind(*args, **kwargs)
                bound.apply_defaults()
                pred = bound.arguments.get('pred', None)
                assert pred is not None and isinstance(pred, list)
                result = [0.0] * len(pred)
            finally:
                signal.alarm(0)
            return result
        return wrapper
    return decorator

class EvalTimeout(type):
    def __new__(mcls, name, bases, namespace):
        if not name.startswith('_'):
            func = namespace.get('eval', None)
            assert func is not None and callable(func)
            assert isinstance(func, staticmethod)
            wrapped = staticmethod(timeout()(func.__func__))
            namespace['eval'] = wrapped
        return super().__new__(mcls, name, bases, namespace)
