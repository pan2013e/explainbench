import json

from deepdiff import DeepDiff
from tracer.protocol import Event, FunctionEvent, ReturnEvent

def load_traces(file_path):
    with open(file_path, 'r') as f:
        traces = [Event.from_dict(json.loads(line)) for line in f]
    return traces

def ignore_order_func(level):
    unordered_fields = ['vars_used', 'vars_defined']
    return any(field in level.path() for field in unordered_fields)

if __name__ == "__main__":
    buggy_traces = load_traces("logs/run_evaluation/validate-gold/gold/astropy__astropy-12907/buggy_traces/astropy/modeling/tests/test_separable.py::test_separable[compound_model9-result9].jsonl")
    patched_traces = load_traces("logs/run_evaluation/validate-gold/gold/astropy__astropy-12907/patched_traces/astropy/modeling/tests/test_separable.py::test_separable[compound_model9-result9].jsonl")
    seen_stmt_change = False
    params_stack = []
    for buggy, patched in zip(buggy_traces, patched_traces):
        if isinstance(patched, FunctionEvent):
            params_stack.append(patched.parameters)
        if isinstance(patched, ReturnEvent):
            params_stack.pop()
        diff = DeepDiff(buggy.model_dump(), patched.model_dump(), significant_digits=3, ignore_order=False, ignore_order_func=ignore_order_func, exclude_paths="root['parameters']")
        if 'statement' in diff.affected_root_keys:
            seen_stmt_change = True
        if seen_stmt_change and 'seen_variables' in diff.affected_root_keys:
            print(f'- {buggy.event_type:<10} {buggy.statement}')
            print(f'+ {patched.event_type:<10} {patched.statement}')
            print(diff.affected_root_keys)
            print(diff)
            print(params_stack[-1])
            print(patched.seen_variables)
            break