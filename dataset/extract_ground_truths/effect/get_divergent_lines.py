from dataset.extract_ground_truths.effect.trace_util import (
    diff_events,
    load_trace_pair
)
from dataset.extract_ground_truths.effect.postprocessing_util import(
    apply_trace_filters, 
    get_complete_variable_views_from_diff
)

def main(instance_id, agent='gold', test_id=0, base_dir=None):
    buggy_traces, patched_traces = load_trace_pair(agent, instance_id, test_id, base_dir)
    buggy_function, patched_function = buggy_traces.entry, patched_traces.entry
    while True:
        try:
            buggy_event = next(buggy_function)
            patched_event = next(patched_function)
        except StopIteration:
            buggy_caller = buggy_function.parent
            patched_caller = patched_function.parent
            if buggy_caller and patched_caller:
                buggy_function = buggy_caller
                patched_function = patched_caller
                continue
            break
        print(f"Buggy ID: {buggy_event.event_id}, Patched ID: {patched_event.event_id}")
        print(f'- {buggy_event.event_type:<10} {buggy_event.statement}')
        print(f'+ {patched_event.event_type:<10} {patched_event.statement}')
        print("========")
        if buggy_function.name == patched_function.name and buggy_event.matches(patched_event):
            event_type = buggy_event.event_type
            if event_type == 'Function':
                buggy_callee = buggy_function.step_into(buggy_event)
                patched_callee = patched_function.step_into(patched_event)
                if (
                    buggy_callee.return_value is None and patched_callee.return_value is None
                    or not buggy_callee.returns_equals(patched_callee)
                ):
                    buggy_function = buggy_callee
                    patched_function = patched_callee
            else:
                # check diff
                repo_name = instance_id.split("__")[0]
                diff = diff_events(buggy_event, patched_event, repo_name)
                filtered_diff = diff
                # apply_trace_filters needs to be fixed
                # need to support event types other than "Line"
                # filtered_diff = apply_trace_filters(diff, patched_event, instance_id)
                if filtered_diff:
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
            print(f'- {buggy_event.event_type:<10} {buggy_event.statement}')
            print(f'+ {patched_event.event_type:<10} {patched_event.statement}')
            # should return something
            break
    return None

if __name__ == "__main__":
    from pprint import pprint
    result = main("astropy__astropy-7336", agent="20250805_openhands-Qwen3-Coder-480B-A35B-Instruct")
    pprint(result)