import logging

from tracer.protocol import Event
from dataset.extract_ground_truths.effect.trace_util import (
    diff_events,
    load_trace_pair,
    Traces,
)
from dataset.extract_ground_truths.effect.postprocessing_util import (
    get_complete_variable_views_from_diff
)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)
print = logger.debug

def get_event_count(event: Event, traces: Traces):
    count = 0
    for e in traces._events:
        if e.line_number == event.line_number and e.event_type == event.event_type:
            count += 1
        if e is event:
            break
    return count

def state_diff(buggy_event: Event, patched_event: Event, repo_name: str, **kwargs):
    diff = diff_events(buggy_event, patched_event, repo_name)
    if diff:
        buggy_variable_views = get_complete_variable_views_from_diff(buggy_event, diff)
        patched_variable_views = get_complete_variable_views_from_diff(patched_event, diff)    
        return {
            "file_path": patched_event.filepath,
            "statement": patched_event.statement,
            "buggy_lineno": buggy_event.line_number,
            "patched_lineno": patched_event.line_number,
            "diff": diff,
            "buggy_variables": buggy_variable_views,
            "patched_variables": patched_variable_views,
            **kwargs
        }
    return None

def main(instance_id, agent='gold', test_id=0, base_dir=None):
    repo_name = instance_id.split("__")[0]
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
                diff = state_diff(
                    buggy_event,
                    patched_event,
                    repo_name,
                    test_id=test_id,
                    function_name=buggy_function.name,
                    buggy_line_count=get_event_count(buggy_event, buggy_traces),
                    patched_line_count=get_event_count(patched_event, patched_traces),
                    buggy_function_param=buggy_function.params,
                    patched_function_param=patched_function.params,
                )
                if diff:
                    return diff
        else:
            print("> Control flow diverged")
            if (
                {buggy_event.event_type, patched_event.event_type} == {"Exception", "Return"}
                and buggy_event.statement == patched_event.statement
            ):
                print(">> Exception vs Return")
                return state_diff(
                    buggy_event,
                    patched_event,
                    repo_name,
                    test_id=test_id,
                    function_name=buggy_function.name,
                    buggy_line_count=get_event_count(buggy_event, buggy_traces),
                    patched_line_count=get_event_count(patched_event, patched_traces),
                    buggy_function_param=buggy_function.params,
                    patched_function_param=patched_function.params,
                )
            if (
                {buggy_event.event_type, patched_event.event_type} == {"Exception", "Line"}
                or {buggy_event.event_type, patched_event.event_type} == {"Exception", "Function"}
            ):
                print(">> Exception vs Line/Function")
                # for line/function event, go to the return event in this function
                break
            print(">> Jumping back to caller")
            buggy_caller = buggy_function.parent
            patched_caller = patched_function.parent
            if buggy_caller and patched_caller:
                buggy_function = buggy_caller
                patched_function = patched_caller
                continue
            break
    return None

if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    result = main("astropy__astropy-12907", agent="20250805_openhands-Qwen3-Coder-480B-A35B-Instruct")
    print(result)