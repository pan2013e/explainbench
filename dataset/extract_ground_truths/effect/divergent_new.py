import os
from dataset.extract_ground_truths.effect.trace_util import (
    diff_events,
    event_match,
    function_match,
    get_trace_dir,
    get_traceback
)
from dataset.extract_ground_truths.effect.trace_util_new import (
    Traces,
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

def load_trace_pair(base_dir, instance_id, test_id=0):
    # test_id refers to the index of FAIL_TO_PASS tests
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    buggy_path = os.path.join(base_dir, instance_id, f"buggy_traces/{test_name}.jsonl")
    patched_path = os.path.join(base_dir, instance_id, f"patched_traces/{test_name}.jsonl")
    buggy_traces = Traces(buggy_path)
    patched_traces = Traces(patched_path)
    return buggy_traces, patched_traces

def main(instance_id, agent='gold', test_id=0):
    base_dir = get_trace_dir(agent)
    buggy_traces, patched_traces = load_trace_pair(base_dir, instance_id, test_id)
    buggy_function, patched_function = buggy_traces.entry, patched_traces.entry
    while True:
        try:
            buggy_event = buggy_function.next_event()
            patched_event = patched_function.next_event()
        except StopIteration:
            print("Reached the end of one trace")
            break
        print(f"Buggy ID: {buggy_event.event_id}, Patched ID: {patched_event.event_id}")
        print(f"Buggy statement: {buggy_event.statement}\nPatched statement: {patched_event.statement}")
        print("========")
        # input()
        if buggy_event.event_type == patched_event.event_type and buggy_event.statement == patched_event.statement and buggy_function.name == patched_function.name:
            event_type = buggy_event.event_type
            if event_type == 'Function':
                # check return value
                # if the same, skip
                # if different, step in
                buggy_called_function = buggy_function.links[buggy_event.event_id]
                patched_called_function = patched_function.links[patched_event.event_id]
                assert buggy_called_function.name == patched_called_function.name
                called_function_name = buggy_called_function.name
                print(f"Stepping into function call: {called_function_name}")
                if buggy_called_function.return_value == patched_called_function.return_value:
                    continue
                else:
                    # if the called function is the patch modified function, stop here
                    if called_function_name.endswith("permutations:__new__"):
                        print("Divergence at function call return value")
                        print(f"Function name: {called_function_name}")
                        print(f"Buggy return value: {serialize(buggy_called_function.return_value)}")
                        print(f"Patched return value: {serialize(patched_called_function.return_value)}")
                        return {
                            "test_id": test_id,
                            "function_name": called_function_name,
                            "buggy_return_value": serialize(buggy_called_function.return_value),
                            "patched_return_value": serialize(patched_called_function.return_value),
                            "buggy_exception": buggy_called_function.exception,
                            "patched_exception": patched_called_function.exception
                        }
                    buggy_function = buggy_called_function
                    patched_function = patched_called_function
                    continue
            # check diff
            repo_name = instance_id.split("__")[0]
            diff = diff_events(buggy_event, patched_event, repo_name)
            filtered_diff = apply_trace_filters(diff, patched_event, instance_id)
            if filtered_diff:
                assert patched_event.filepath == buggy_event.filepath
                # assert patched_block.params == buggy_block.params
                buggy_variable_views = get_complete_variable_views_from_diff(buggy_event,filtered_diff)
                patched_variable_views = get_complete_variable_views_from_diff(patched_event, filtered_diff)
                
                # patched_caller_exp = None
                # buggy_caller_exp = None
                # if hasattr(patched_block, "call_event") and patched_block.call_event:
                #     patched_caller_exp =  patched_block.call_event.statement
                    
                # if hasattr(buggy_block, "call_event") and buggy_block.call_event:
                #     buggy_caller_exp = buggy_block.call_event.statement
                
                # patched_callee_return_val = None
                # if hasattr(patched_block, "return_event") and hasattr(patched_block.return_event, "return_value"):
                #     patched_callee_return_val = patched_block.return_event.return_value

                # buggy_callee_return_val = None
                # if hasattr(buggy_block, "return_event") and hasattr(buggy_block.return_event, "return_value"):
                #     buggy_callee_return_val = buggy_block.return_event.return_value
                    
                return {
                    "test_id": test_id,
                    "file_path": patched_event.filepath,
                    "statement": patched_event.statement,
                    "buggy_lineno": buggy_event.line_number,
                    # "buggy_line_count": get_event_count(buggy_event, buggy_traces),
                    "patched_lineno": patched_event.line_number,
                    # "patched_line_count": get_event_count(patched_event, patched_traces),
                    "filtered_diff": filtered_diff,
                    "function_name": patched_function.name,
                    "buggy_function_param": buggy_function.params,
                    "patched_function_param": patched_function.params,
                    "buggy_variables": buggy_variable_views,
                    "patched_variables": patched_variable_views,
                    # "patched_caller_expression": patched_caller_exp,
                    # "patched_callee_return_value": patched_callee_return_val,
                    # "buggy_caller_expression": buggy_caller_exp,
                    # "buggy_callee_return_value": buggy_callee_return_val

                }
        else:
            print("Control flow diverged")
            print(f"Buggy id: {buggy_event.event_id}, Patched id: {patched_event.event_id}")
            print(f"Buggy function: {buggy_function.name}, Patched function: {patched_function.name}")
            print(f"Buggy statement: {buggy_event.statement}\nPatched statement: {patched_event.statement}")
            # control flow diverged

if __name__ == "__main__":
    from pprint import pprint
    result = main("sympy__sympy-12481", agent="20250805_openhands-Qwen3-Coder-480B-A35B-Instruct")
    pprint(result)