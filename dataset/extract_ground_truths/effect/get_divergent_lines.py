import os
from pathlib import Path
from dataset.extract_ground_truths.effect.trace_util import (
    Traces,
    diff_events,
    event_match,
    function_match,
    apply_trace_filters
)
from dataset.extract_ground_truths.effect.process_agent_patch import (
    get_diff_info_per_instance
)
from execution.util import get_fail_to_pass_tests
from tracer.serializer import serialize

BASE = "/home/zhiyuan/explainbench/logs/run_evaluation/trace.validate-gold.1021/gold"

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
    # for buggy_block in buggy_traces:
    #     print(buggy_block.function_name)
    # print("=====")
    # for patched_block in patched_traces:
    #     print(patched_block.function_name)
    # print("=====")
    # function_match(buggy_traces, patched_traces)
    # exit(0)
    for buggy_block, patched_block in function_match(buggy_traces, patched_traces):
        # Before the divergence point, the function call chain should be the same
        try:
            assert buggy_block.function_name == patched_block.function_name, f"Function names differ: {buggy_block.function_name} vs {patched_block.function_name}"
        except AssertionError:
            breakpoint()
        for buggy_event, patched_event in event_match(buggy_block, patched_block):
            assert buggy_event.statement == patched_event.statement
            # Exit when event types differ, usually means test exception raised
            if buggy_event.event_type != patched_event.event_type:
                break
            repo_name = instance_id.split("__")[0]
            diff = diff_events(buggy_event, patched_event, repo_name)            
            print(f"Buggy id: {buggy_event.event_id}, Patched id: {patched_event.event_id}")
            print('In function: ', patched_block.function_name)
            print(f'- {buggy_event.event_type:<10} {buggy_event.statement}')
            print(f'+ {patched_event.event_type:<10} {patched_event.statement}')
            filtered_diff = apply_trace_filters(diff, patched_event)            
            if 'seen_variables' in diff.affected_root_keys and filtered_diff:
                # return {
                #     'buggy': buggy_event.model_dump(),
                #     'patched': patched_event.model_dump(),
                #     'filtered_diff': serialize(filtered_diff),
                # }
                print('Diff: ', filtered_diff)
                # assert patched_block.params == buggy_block.params, f"CHECK: Function parameters differ in prepatch and postpatch, buggy: {buggy_block.params}, patched: {patched_block.params}"
                # print('Function parameters: ', patched_block.params)
                if hasattr(patched_event, 'seen_variables'):
                    print('Buggy Variables: ', buggy_event.seen_variables)
                    print('====')
                    print('Patched Variables: ', patched_event.seen_variables)
                input('...')
            # input("....")
        #         is_break = True
        #         break
        # if is_break:
        #     break


if __name__ == "__main__":
    main("astropy__astropy-13453")