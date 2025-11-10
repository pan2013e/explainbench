import os
import json
import argparse
import warnings

from tqdm.auto import tqdm
from evaluation.inference import Model
from evaluation.task import Task
from evaluation.util import (
    load_context,
    load_explanation,
    load_ground_truth,
    result_statistics,
)

def get_path(task: type[Task], model: Model, agent_id: str, mode: str):
    return f'results/{mode}/{task.repr()}/{agent_id}__{model.model_id.replace("/", "-")}.json'

def generate(task: type[Task], model: Model, agent_id: str):
    explanations = load_explanation(agent_id)
    context = load_context(task, agent_id)
    if context is None:
        context = [{}] * len(explanations)
    assert len(explanations) == len(context), f'Number of context items ({len(context)}) does not match number of explanations ({len(explanations)})'
    pred_results = {}
    pbar = tqdm(zip(explanations.items(), context), total=len(explanations))
    for (instance_id, expl), ctx in pbar:
        pbar.set_postfix(**model.tqdm_usage())
        expl = expl[0] if expl else ''
        pred = task.predict(model, expl, **ctx)
        pred_results[instance_id] = [p.model_dump() for p in pred]
    save_path = get_path(task, model, agent_id, 'generation')
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    if os.path.exists(save_path):
        warnings.warn(f'Overwriting existing generation file: {save_path}')
    with open(save_path, 'w') as f:
        json.dump({
            'token_usage': model.token_usage,
            'predictions': pred_results
        }, f, indent=2)

def evaluate(task: type[Task], model: Model, agent_id: str):
    pred_path = get_path(task, model, agent_id, 'generation')
    if not os.path.exists(pred_path):
        raise FileNotFoundError(f'Prediction file not found: {pred_path}')
    with open(pred_path, 'r') as f:
        pred_json = json.load(f)['predictions']
    pred_data = {k: [task.SCHEMA.model_validate(item) for item in v] for k, v in pred_json.items()}
    gt_data = {item['instance_id']: item for item in load_ground_truth()}
    zipped = []
    for instance_id, pred in pred_data.items():
        if instance_id not in gt_data:
            raise ValueError(f'Instance ID {instance_id} not found in ground truth')
        zipped.append((instance_id, pred, gt_data[instance_id]))
    eval_results = {}
    for instance_id, pred, gt in tqdm(zipped):
        eval_results[instance_id] = task.eval(pred, gt)
    save_path = get_path(task, model, agent_id, 'evaluation')
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    if os.path.exists(save_path):
        warnings.warn(f'Overwriting existing evaluation file: {save_path}')
    with open(save_path, 'w') as f:
        json.dump({
            'statistics': result_statistics(eval_results),
            'raw': eval_results,
        }, f, indent=2)

def main(task: type[Task], model: Model, agent_id: str):
    generate(task, model, agent_id)
    evaluate(task, model, agent_id)

if __name__ == '__main__':
    argparser = argparse.ArgumentParser(
        prog='evaluation.main',
        epilog='Available tasks: ' + ', '.join(Task._registry.keys()),
    )
    argparser.add_argument('task', type=str, help='Evaluation task to run')
    argparser.add_argument('-a', '--agent', type=str, required=True, help='ID of agent producing the explanations')
    argparser.add_argument('-m', '--model', type=str, default='gemini/gemini-2.5-flash-lite', help='LLM used for question answering')
    argparser.add_argument('-n', '--num-generations', type=int, default=5, help='Number of generations per instance')
    argparser.add_argument('-go', '--gen-only', action='store_true', help='Only generate predictions')
    argparser.add_argument('-eo', '--eval-only', action='store_true', help='Only evaluate existing predictions')
    args = argparser.parse_args()
    task = Task.get_task(args.task)
    if args.gen_only and args.eval_only:
        raise ValueError('Cannot set both --gen-only and --eval-only')
    if args.num_generations < 1:
        raise ValueError('Number of generations must be at least 1')
    model = Model(args.model, n=args.num_generations)
    if args.gen_only:
        entry_fn = generate
    elif args.eval_only:
        entry_fn = evaluate
    else:
        entry_fn = main
    entry_fn(task, model, args.agent)