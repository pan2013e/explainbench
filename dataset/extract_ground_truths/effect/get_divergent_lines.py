import os

from dataset.extract_ground_truths.effect.trace_util import (
    load_traces,
    diff_events,
)
from execution.util import get_fail_to_pass_tests

BASE = "logs/run_evaluation/validate-gold.1021/gold"

def load_trace_pair(instance_id, test_id=0):
    # test_id refers to the index of FAIL_TO_PASS tests
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    buggy_path = os.path.join(BASE, instance_id, "buggy_traces", f"{test_name}.jsonl")
    patched_path = os.path.join(BASE, instance_id, "patched_traces", f"{test_name}.jsonl")
    buggy_traces = load_traces(buggy_path)
    patched_traces = load_traces(patched_path)
    return buggy_traces, patched_traces

def main(instance_id, test_id=0):
    # use the first FAIL_TO_PASS test case, should allow specifying test_id later
    buggy_traces, patched_traces = load_trace_pair(instance_id, test_id)
    for buggy_block, patched_block in zip(buggy_traces, patched_traces):
        # Before the divergence point, the function call chain should be the same
        if buggy_block.function_name != patched_block.function_name:
            exit(0)
        for buggy_event, patched_event in zip(buggy_block, patched_block):
            # If code lines differ, stop comparing further for now
            if buggy_event.statement != patched_event.statement:
                exit(0)
            diff = diff_events(buggy_event, patched_event)
            if 'seen_variables' in diff.affected_root_keys:
                print('In function: ', patched_block.function_name)
                print(f'- {buggy_event.event_type:<10} {buggy_event.statement}')
                print(f'+ {patched_event.event_type:<10} {patched_event.statement}')
                print('Diff: ', diff)
                assert patched_block.params == buggy_block.params, f"CHECK: Function parameters differ in prepatch and postpatch, buggy: {buggy_block.params}, patched: {patched_block.params}"
                print('Function parameters: ', patched_block.params)
                if hasattr(patched_event, 'seen_variables'):
                    print('Buggy Variables: ', buggy_event.deserialized().seen_variables)
                    print('====')
                    print('Variables: ', patched_event.deserialized().seen_variables)
                input('===')
