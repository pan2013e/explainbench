import os

from pathlib import Path
from dataset.extract_ground_truths.effect.trace_util import (
    Traces,
    diff_events,
    lcs_event_match,
    filter_based_on_type_changes,
    filter_based_on_used_vars,
    filter_based_on_vars_at_current_line,
    count_changed_vars
)
from dataset.extract_ground_truths.effect.process_agent_patch import (
    get_diff_info_per_instance
)
from execution.util import get_fail_to_pass_tests

BASE = "/home/zhiyuan/explainbench/logs/run_evaluation/validate-gold.1021/gold"

def load_trace_pair(instance_id, diff_lines, test_id=0):
    # test_id refers to the index of FAIL_TO_PASS tests
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    buggy_path = os.path.join(BASE, instance_id, "buggy_traces", f"{test_name}.jsonl")
    patched_path = os.path.join(BASE, instance_id, "patched_traces", f"{test_name}.jsonl")
    buggy_traces = Traces(buggy_path, diff_lines, 'buggy')
    patched_traces = Traces(patched_path, diff_lines, 'patched')
    return buggy_traces, patched_traces

def main(instance_id, test_id=0):
    diff_lines = get_diff_info_per_instance(
        Path(BASE),
        Path(instance_id)
    )
    # use the first FAIL_TO_PASS test case, should allow specifying test_id later
    buggy_traces, patched_traces = load_trace_pair(instance_id, diff_lines, test_id)
    for buggy_block, patched_block in zip(buggy_traces, patched_traces):
        # Before the divergence point, the function call chain should be the same
        assert buggy_block.function_name == patched_block.function_name
        for buggy_event, patched_event in lcs_event_match(buggy_block, patched_block):
            assert buggy_event.statement == patched_event.statement
            # Exit when event types differ, usually means test exception raised
            if buggy_event.event_type != patched_event.event_type:
                break
            diff = diff_events(buggy_event, patched_event)            
            print(f"Buggy id: {buggy_event.event_id}, Patched id: {patched_event.event_id}")
            print('In function: ', patched_block.function_name)
            print(f'- {buggy_event.event_type:<10} {buggy_event.statement}')
            print(f'+ {patched_event.event_type:<10} {patched_event.statement}')
            
            if 'seen_variables' in diff.affected_root_keys:
                n_changed = count_changed_vars(diff)
                filtered_diff = diff.copy()
                for filter_func in (filter_based_on_vars_at_current_line, filter_based_on_type_changes, filter_based_on_used_vars):
                    filtered_diff = filter_func(filtered_diff, patched_event)
                    n_changed = count_changed_vars(filtered_diff)
                    if n_changed == 1:
                        diff = filtered_diff.copy()
                        break
                print('Diff: ', diff)
                # assert patched_block.params == buggy_block.params, f"CHECK: Function parameters differ in prepatch and postpatch, buggy: {buggy_block.params}, patched: {patched_block.params}"
                print('Function parameters: ', patched_block.params)
                if hasattr(patched_event, 'seen_variables'):
                    print('Buggy Variables: ', buggy_event.deserialized().seen_variables)
                    print('====')
                    print('Variables: ', patched_event.deserialized().seen_variables)
                input("....")

if __name__ == "__main__":
    main("astropy__astropy-14508")