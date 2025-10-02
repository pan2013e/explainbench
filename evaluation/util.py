import os
import json

from typing import Any, Callable

DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(DIR, '..', 'dataset')

def is_subpath(abs: str, rel: str):
    if len(abs) < len(rel):
        abs, rel = rel, abs
    abs = os.path.normpath(abs)
    rel = os.path.normpath(rel)
    return abs == rel or abs.endswith(os.path.sep + rel)

def f1_score(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp > 0 else 0.0
    r = tp / (tp + fn) if tp + fn > 0 else 0.0
    return 2 * p * r / (p + r) if p + r > 0 else 0.0

def set_f1_score(pred: set, gt: set, equal_fn: Callable[[Any, Any], bool] = lambda x, y: x == y):
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
