import os
import json
import numpy as np

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

def is_line_equal(pred, gt):
    if not is_subpath(pred[0], gt[0]):
        return False
    if isinstance(pred[1], int):
        return pred[1] == gt[1]
    elif isinstance(pred[1], str):
        return pred[1].strip() == gt[2].strip()
    raise ValueError(f'Unknown line type: {type(pred[1])}')

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

def load_explanation(split: str):
    with open(os.path.join(DATASET_DIR, 'explanations', 'dataset.json')) as f:
        data = json.load(f)[split]
    return data

def load_ground_truth():
    with open(os.path.join(DATASET_DIR, 'extract_ground_truths', 'ground_truth.jsonl')) as f:
        data = [json.loads(line) for line in f]
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