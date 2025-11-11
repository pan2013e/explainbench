import os
from dataset.extract_ground_truths.effect.trace_util import (
    Traces,
    diff_events,
    event_match,
    function_match,
    get_trace_dir,
)
from dataset.extract_ground_truths.effect.postprocessing_util import(
    apply_trace_filters, 
    get_complete_variable_views_from_diff
)
from dataset.extract_ground_truths.effect.process_agent_patch import (
    get_diff_info_per_instance
)
from execution.util import get_fail_to_pass_tests
from tracer.serializer import serialize

def load_trace_pair(base_dir, instance_id, diff_lines, test_id=0):
    # test_id refers to the index of FAIL_TO_PASS tests
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    buggy_path = os.path.join(base_dir, instance_id, f"buggy_traces/{test_name}.jsonl")
    patched_path = os.path.join(base_dir, instance_id, f"patched_traces/{test_name}.jsonl")
    buggy_traces = Traces(buggy_path, diff_lines, 'buggy')
    patched_traces = Traces(patched_path, diff_lines, 'patched')
    return buggy_traces, patched_traces

def get_event_count(event, traces: Traces):
    count = 0
    for e in traces.events:
        if e.line_number == event.line_number:
            count += 1
        if e is event:
            break
    return count

def main(instance_id, agent='gold', test_id=0, is_return=False, base_dir=None):
    if not base_dir:
        base_dir = get_trace_dir(agent)
    diff_lines = get_diff_info_per_instance(base_dir, instance_id)
    # use the first FAIL_TO_PASS test case, should allow specifying test_id later
    buggy_traces, patched_traces = load_trace_pair(base_dir, instance_id, diff_lines, test_id)
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
            if not is_return:            
                print(f"Buggy id: {buggy_event.event_id}, Patched id: {patched_event.event_id}")
                print('In function: ', patched_block.function_name)
                print(f'- {buggy_event.event_type:<10} {buggy_event.statement}')
                print(f'+ {patched_event.event_type:<10} {patched_event.statement}')
            filtered_diff = apply_trace_filters(diff, patched_event, instance_id)
            # Debugging
            if filtered_diff:
                if is_return:
                    assert patched_event.filepath == buggy_event.filepath
                    assert patched_block.params == buggy_block.params
                    buggy_variable_views = get_complete_variable_views_from_diff(buggy_event,filtered_diff)
                    patched_variable_views = get_complete_variable_views_from_diff(patched_event, filtered_diff)
                    return {
                        "file_path": patched_event.filepath,
                        "buggy_lineno": buggy_event.line_number,
                        "buggy_line_count": get_event_count(buggy_event, buggy_traces),
                        "patched_lineno": patched_event.line_number,
                        "patched_line_count": get_event_count(patched_event, patched_traces),
                        "filtered_diff": filtered_diff,
                        "function_name": patched_block.function_name,
                        "function_param": patched_block.params,
                        "buggy_variables": buggy_variable_views,
                        "patched_variables": patched_variable_views,
                    }
                print("Diff: ", filtered_diff)            
                if 'return_value' in diff.affected_root_keys and hasattr(patched_event, "return_value"):
                    print('Buggy Variables: ', buggy_event.return_value)
                    print('====')
                    print('Patched Variables: ', patched_event.return_value)
                    input('...')
                if 'seen_variables' in diff.affected_root_keys and hasattr(patched_event, 'seen_variables'):
                    print('Buggy Variables: ', buggy_event.seen_variables)
                    print('====')
                    print('Patched Variables: ', patched_event.seen_variables)
                    input('...')

if __name__ == "__main__":
    import pprint as pp
    test = main("astropy__astropy-7166", is_return=True, base_dir="/home/yusuf/explainbench/logs_zhiyuan/logs/run_evaluation/trace.gold.1021/gold")
    pp.pprint(test)