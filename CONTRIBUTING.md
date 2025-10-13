# Developing Guidelines

## Environment Setup and Usage

Please refer to [README.md](README.md).

## Add a task

1. In `evaluation/schema.py`, create a new class inheriting from `BaseModel`. This defines the output schema of the LLM's response. Make sure the class is JSON-serializable.
2. In `evaluation/task.py`, create a new class inheriting from `Task`. Implement the three following fields and methods:
```py
from evaluation import schema

class MyTask(Task[schema.MySchema]):
    #                    ^^^^^^^^ Class defined in step 1
    QUESTION = ... # The question to ask the LLM
    SCHEMA = schema.MySchema

    @staticmethod
    def eval(pred: list[schema.MySchema], gt: dict): # Should return list[float]
        '''
        Batched evaluation function.

        Args:
        - pred: List of model predictions with length n (repeated n times for a dataset instance)
        - gt: Ground truth data for the dataset instance. Please refer to [dataset/extract_ground_truths/ground_truth.jsonl](dataset/extract_ground_truths/ground_truth.jsonl).
        '''
        # Evaluation logic here
        pass
```
No further steps are required after this. The task class will be automatically inferred at evaluation entry with its lowercase qualified name (e.g. `MyTask` -> `mytask`, `RootCause.File` -> `rootcause.file`).