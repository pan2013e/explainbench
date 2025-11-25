import os
import json
import signal
import inspect
import warnings
import numpy as np

from functools import wraps
from operator import eq
from typing import Any, Callable

DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(DIR, '..', 'dataset')

SWEBENCH_VERIFIED_PROJECT_PREFIX = [
    'astropy',
    'django',
    'lib/matplotlib',
    'seaborn',
    'src/flask',
    'requests',
    'xarray',
    'pylint',
    'src/_pytest',
    'sklearn',
    'sphinx',
    'sympy'
]

def is_subpath(abs: str, rel: str):
    if len(abs) < len(rel):
        abs, rel = rel, abs
    abs = os.path.normpath(abs)
    rel = os.path.normpath(rel)
    return abs == rel or (any(rel.startswith(prefix) for prefix in SWEBENCH_VERIFIED_PROJECT_PREFIX) and abs.endswith(os.path.sep + rel))

def simple_name_eq(a: tuple[str, str], b: tuple[str, str]):
    if a[1] != b[1]:
        return False
    a_simple = a[0].split('.')[-1]
    b_simple = b[0].split('.')[-1]
    return a_simple == b_simple

def f1_score(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp > 0 else 0.0
    r = tp / (tp + fn) if tp + fn > 0 else 0.0
    return 2 * p * r / (p + r) if p + r > 0 else 0.0

def set_f1_score(pred: set, gt: set, equal_fn: Callable[[Any, Any], bool] = eq):
    matched_gt = set()
    tp = 0
    for p in pred:
        for g in gt:
            if g not in matched_gt and equal_fn(p, g):
                tp += 1
                matched_gt.add(g)
                break
    fp = len(pred) - tp
    fn = len(gt) - tp
    return f1_score(tp, fp, fn)

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
        func = namespace.get('eval', None)
        assert func is not None and callable(func)
        assert isinstance(func, staticmethod)
        wrapped = staticmethod(timeout()(func.__func__))
        namespace['eval'] = wrapped
        return super().__new__(mcls, name, bases, namespace)
