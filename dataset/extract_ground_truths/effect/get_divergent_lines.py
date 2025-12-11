import logging

from tracer.protocol import Event, LineEvent
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

RANDOMIZED_FUNCTIONS = [
    'django.contrib.auth.base_user:AbstractBaseUser.set_password',
    'django.core.cache.backends.base:BaseCache.get_backend_timeout',
]

def get_event_count(event: Event, traces: Traces):
    count = 0
    for e in traces._events:
        if e.line_number == event.line_number:
            count += 1
        if e is event:
            break
    return count

def location_to_present(buggy_event: Event):
    if buggy_event.event_type == 'Exception' or buggy_event.event_type == 'Return':
        return "The return statement in the provided function"
    else:
        return buggy_event.statement

def before_or_after(buggy_event: Event, patched_event: Event):
    if (
        'Exception' in {buggy_event.event_type, patched_event.event_type}
        or 'Return' in {buggy_event.event_type, patched_event.event_type}
    ):
        return 'after'
    else:
        return 'before'

def state_diff(buggy_event: Event, patched_event: Event, repo_name: str, **kwargs):
    diff = diff_events(buggy_event, patched_event, repo_name)
    if diff:
        logger.debug(f"> State diff found at Buggy ID {buggy_event.event_id} vs Patched ID {patched_event.event_id}")
        logger.debug(f"Function: {buggy_event.function_name} vs {patched_event.function_name}")
        logger.debug(f'- {buggy_event.event_type:<10} {buggy_event.statement}')
        logger.debug(f'+ {patched_event.event_type:<10} {patched_event.statement}')
        logger.debug("========")
        buggy_variable_views = get_complete_variable_views_from_diff(buggy_event, diff)
        patched_variable_views = get_complete_variable_views_from_diff(patched_event, diff)
        for k, v in kwargs.items():
            if callable(v):
                kwargs[k] = v()
        return {
            "file_path": patched_event.filepath,
            "buggy_event_id": buggy_event.event_id,
            "patched_event_id": patched_event.event_id,
            "buggy_event_type": buggy_event.event_type,
            "patched_event_type": patched_event.event_type,
            "buggy_statement": buggy_event.statement,
            "patched_statement": patched_event.statement,
            "location": location_to_present(buggy_event),
            "before_or_after": before_or_after(buggy_event, patched_event),
            "buggy_lineno": buggy_event.line_number,
            "patched_lineno": patched_event.line_number,
            "diff": diff.to_dict() if hasattr(diff, "to_dict") else diff,
            "buggy_variables": buggy_variable_views,
            "patched_variables": patched_variable_views,
            **kwargs
        }
    return None

def main(instance_id, agent='gold', test_id=0, base_dir=None):
    repo_name = instance_id.split("__")[0]
    buggy_traces, patched_traces = load_trace_pair(agent, instance_id, test_id, base_dir)
    buggy_function, patched_function = buggy_traces.entry, patched_traces.entry
    is_pmf_exist = len(buggy_traces._pmf) > 0 or len(patched_traces._pmf) > 0
    if is_pmf_exist:
        logger.debug(">> Patch modified function exist!")
    diffing_started = False if is_pmf_exist else True
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
            logger.debug("> END")
            break
        if not diffing_started and (buggy_function.is_pmf or patched_function.is_pmf):
            logger.debug(f">> Start Diffing Now")
            diffing_started = True
        logger.debug(f"Buggy ID: {buggy_event.event_id}, Patched ID: {patched_event.event_id}")
        logger.debug(f"Function: {buggy_function.name} vs {patched_function.name}")
        logger.debug(f'- {buggy_event.event_type:<10} {buggy_event.statement}')
        logger.debug(f'+ {patched_event.event_type:<10} {patched_event.statement}')
        logger.debug("========")
        if buggy_function.name == patched_function.name and buggy_event.matches(patched_event):
            event_type = buggy_event.event_type
            if event_type == 'Function':
                buggy_callee = buggy_function.step_into(buggy_event)
                patched_callee = patched_function.step_into(patched_event)
                if (
                    buggy_callee.return_value is None and patched_callee.return_value is None
                    or not buggy_callee.returns_equals(patched_callee)
                ) and all(not buggy_callee.name.endswith(s) for s in [
                    '<genexpr>', '<listcomp>', '<dictcomp>', '<setcomp>', '<lambda>'
                ]) and buggy_callee.name not in RANDOMIZED_FUNCTIONS:
                    if buggy_callee.is_pmf:
                        logger.debug(">> Step into patch-modified function")
                        logger.debug(">> Directly go to the return point")
                    buggy_function = buggy_callee
                    patched_function = patched_callee
            else:
                if not diffing_started:
                    continue
                diff = state_diff(
                    buggy_event,
                    patched_event,
                    repo_name,
                    test_id=test_id,
                    function_name=buggy_function.name,
                    buggy_line_count=lambda: get_event_count(buggy_event, buggy_traces),
                    patched_line_count=lambda: get_event_count(patched_event, patched_traces),
                    buggy_function_param=buggy_function.params,
                    patched_function_param=patched_function.params,
                    instance_id=instance_id,
                    agent=agent,
                )
                if diff:
                    if isinstance(buggy_event, LineEvent) and isinstance(patched_event, LineEvent):
                        buggy_variables = diff['buggy_variables'].keys() | diff['patched_variables'].keys()
                        function_param_names = (buggy_function.params.keys() if isinstance(buggy_function.params, dict) else set()) | (patched_function.params.keys() if isinstance(patched_function.params, dict) else set())
                        if buggy_variables & function_param_names:
                            logger.debug(">> Function parameters reveal the divergence")
                            logger.debug(">> Buggy variable names: " + ", ".join(sorted(buggy_variables)))
                            logger.debug(">> Parameter names: " + ", ".join(sorted(function_param_names)))
                            logger.debug(">> Jumping back to caller")
                            buggy_caller = buggy_function.parent
                            patched_caller = patched_function.parent
                            if buggy_caller and patched_caller:
                                buggy_function = buggy_caller
                                patched_function = patched_caller
                                continue
                            logger.debug("> END")
                            break
                    return diff
        else:
            logger.debug("> Control flow diverged")
            lhs_event = buggy_function.return_event
            rhs_event = patched_function.return_event
            diff = {}
            if diffing_started:
                diff = state_diff(
                    lhs_event,
                    rhs_event,
                    repo_name,
                    test_id=test_id,
                    function_name=buggy_function.name,
                    buggy_line_count=lambda: get_event_count(lhs_event, buggy_traces),
                    patched_line_count=lambda: get_event_count(rhs_event, patched_traces),
                    buggy_function_param=buggy_function.params,
                    patched_function_param=patched_function.params,
                    instance_id=instance_id,
                    agent=agent,
                )
            if diff:
                return diff
            else:
                logger.debug(">> No diff found at return point")
                logger.debug(">> Jumping back to caller")
                buggy_caller = buggy_function.parent
                patched_caller = patched_function.parent
                if buggy_caller and patched_caller:
                    buggy_function = buggy_caller
                    patched_function = patched_caller
                    continue
                logger.debug("> END")
                break
    return {}

if __name__ == "__main__":
    import sys
    instance_id = sys.argv[1]
    logger.setLevel(logging.DEBUG)
    # from pprint import pprint
    result = main(f"django__django-{instance_id}", test_id=0,  agent="20250805_openhands-Qwen3-Coder-480B-A35B-Instruct")
    print(result)