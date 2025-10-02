import argparse

from evaluation.inference import Model
from evaluation.task import Task, ALL_TASKS

def main(task: Task, model_id: str):
    model = Model(model_id)
    ...

if __name__ == '__main__':
    argparser = argparse.ArgumentParser()
    argparser.add_argument('task', type=str, required=True)
    argparser.add_argument('--model', type=str, default='gemini/gemini-2.5-flash')
    args = argparser.parse_args()
    if args.task not in ALL_TASKS:
        raise ValueError(f'Unknown task {args.task}, available tasks: {list(ALL_TASKS.keys())}')
    main(ALL_TASKS[args.task], args.model)