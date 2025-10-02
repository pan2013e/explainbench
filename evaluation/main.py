import os
import json
import argparse
import warnings

from tqdm.auto import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
from evaluation.inference import Model
from evaluation.task import Task, NAME_TASK_MAP, TASK_NAME_MAP
from evaluation.util import load_explanation, load_ground_truth

def get_path(task: Task, model: Model, agent_id: str, mode: str):
    return f'results/{mode}/{TASK_NAME_MAP[task].replace(".", "_")}/{agent_id}__{model.model_id.replace("/", "-")}.json'

def generate(task: Task, model: Model, agent_id: str):
    explanations = load_explanation(agent_id)
    pred_results = {}
    pbar = tqdm(explanations.items())
    for idx, (instance_id, expl) in enumerate(pbar):
        pbar.set_postfix(**model.tqdm_usage())
        # use subset for now
        if idx == 101: break
        expl = expl[0] if expl else ''
        pred = task.predict(model, expl)
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

def evaluate(task: Task, model: Model, agent_id: str):
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
    with ProcessPoolExecutor(max_workers=os.cpu_count()//4) as executor:
        futures = {executor.submit(task.eval, pred, gt): instance_id for instance_id, pred, gt in zipped}
        for future in tqdm(as_completed(list(futures.keys())), total=len(futures)):
            instance_id = futures[future]
            try:
                result = future.result()
                eval_results[instance_id] = result
            except Exception as e:
                print(f'Error evaluating instance {instance_id}: {e}')
    save_path = get_path(task, model, agent_id, 'evaluation')
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    if os.path.exists(save_path):
        warnings.warn(f'Overwriting existing evaluation file: {save_path}')
    with open(save_path, 'w') as f:
        json.dump(eval_results, f, indent=2)

def main(task: Task, model: Model, agent_id: str):
    generate(task, model, agent_id)
    evaluate(task, model, agent_id)

if __name__ == '__main__':
    argparser = argparse.ArgumentParser()
    argparser.add_argument('task', type=str, help='Evaluation task to run')
    argparser.add_argument('-a', '--agent', type=str, required=True, help='ID of agent producing the explanations')
    argparser.add_argument('-m', '--model', type=str, default='gemini/gemini-2.5-flash-lite', help='LLM used for question answering')
    argparser.add_argument('-n', '--num-generations', type=int, default=1, help='Number of generations per instance')
    argparser.add_argument('-go', '--gen-only', action='store_true', help='Only generate predictions')
    argparser.add_argument('-eo', '--eval-only', action='store_true', help='Only evaluate existing predictions')
    args = argparser.parse_args()
    if args.task not in NAME_TASK_MAP:
        raise ValueError(f'Unknown task {args.task}, available tasks: {list(NAME_TASK_MAP.keys())}')
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
    entry_fn(NAME_TASK_MAP[args.task], model, args.agent)