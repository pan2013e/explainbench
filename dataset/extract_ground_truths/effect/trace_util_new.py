import os
import json

from deepdiff import DeepDiff
from tracer.protocol import (
    Event,
    FunctionEvent,
    ReturnEvent,
    ExceptionEvent,
)
from execution.util import get_fail_to_pass_tests

DIR = os.path.dirname(os.path.abspath(__file__))

def load_traces(file_path):
    with open(file_path, 'r') as f:
        return [Event.from_dict(json.loads(line)) for line in f]

def get_trace_dir(agent='gold'):
    return "/home/yusuf/explainbench/logs_zhiyuan/logs/run_evaluation/trace.debug.20250805_openhands-Qwen3-Coder-480B-A35B-Instruct.1021/20250805_openhands-Qwen3-Coder-480B-A35B-Instruct"

def load_trace_pair(agent, instance_id, test_id=0, base_dir=None):
    # test_id refers to the index of FAIL_TO_PASS tests
    if base_dir is None:
        base_dir = get_trace_dir(agent)
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    buggy_path = os.path.join(base_dir, instance_id, f"buggy_traces/{test_name}.jsonl")
    patched_path = os.path.join(base_dir, instance_id, f"patched_traces/{test_name}.jsonl")
    buggy_traces = Traces(buggy_path)
    patched_traces = Traces(patched_path)
    return buggy_traces, patched_traces

def rv_equals(rv1, rv2):
    diff = DeepDiff(rv1, rv2, significant_digits=5, ignore_private_variables=False)
    return diff == {}

class FunctionBlock:
    def __init__(self, id, name, parent, params=None):
        self.id = id
        self.name = name
        self.parent = parent     # type: FunctionBlock | None
        self.params = params
        self.return_value = None # type: any | None
        self.exception = None    # type: tuple[str, str] | None
        self._events = []        # type: list[Event]
        self._links = {}         # type: dict[int, FunctionBlock]
        self._index = 0
        
    def add_event(self, event: Event):
        self._events.append(event)
    
    def prev_event(self, event: Event):
        idx = self._events.index(event)
        if idx > 0:
            return self._events[idx - 1]
        return None
    
    def step_into(self, event: FunctionEvent):
        assert isinstance(event, FunctionEvent), "Not a FunctionEvent"
        return self._links[event.event_id]
    
    def returns_equals(self, other):
        assert isinstance(other, FunctionBlock), "Not a FunctionBlock"
        match self.return_value, self.exception, other.return_value, other.exception:
            # case rv1, e1, rv2, e2:
            #     return e1 == e2 and rv_equals(rv1, rv2)
            case rv1, None, rv2, None:
                return rv_equals(rv1, rv2)
            case None, e1, None, e2:
                return e1 == e2
            case (_, None, None, _) | (None, _, _, None):
                return False
            case _:
                raise ValueError("Exception and return value cannot coexist")
    
    def __iter__(self):
        return self
    
    def __next__(self):
        if self._index >= len(self._events):
            raise StopIteration
        event = self._events[self._index]
        self._index += 1
        return event

class Traces:
    def __init__(self, trace_path: str):
        self._entry = FunctionBlock(-1, "<module>", None)
        self._events = load_traces(trace_path)
        self._build_traces()

    def _build_traces(self):
        stack = [self._entry]
        for idx, e in enumerate(self._events):
            stack[-1].add_event(e)
            match e:
                case FunctionEvent():
                    new_block = FunctionBlock(e.event_id, e.function_name, stack[-1], params=e.parameters)
                    stack[-1]._links[e.event_id] = new_block
                    stack.append(new_block)
                case ReturnEvent():
                    stack[-1].return_value = e.return_value
                    stack.pop()
                case ExceptionEvent():
                    # stack[-1].exception = (e.exception_type, e.exception_value)
                    ne = self._events[idx + 1] if idx + 1 < len(self._events) else None
                    if isinstance(ne, ReturnEvent):
                        stack[-1].exception = (e.exception_type, e.exception_value)
                case _: pass

    @property
    def entry(self):
        fbs = list(self._entry._links.values())
        assert len(fbs) > 0, "<module> does not call any test functions"
        return fbs[0]
