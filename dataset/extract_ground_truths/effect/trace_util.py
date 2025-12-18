import os
import mmap
import json
import orjson

from deepdiff import DeepDiff
from tracer.protocol import (
    Event,
    LineEvent,
    FunctionEvent,
    ReturnEvent,
    ExceptionEvent,
)
from execution.util import get_fail_to_pass_tests
from dataset.extract_ground_truths.effect.process_agent_patch import get_diff_info_per_instance
from dataset.extract_ground_truths.effect.postprocessing_util import get_ignore_order_func

DIR = os.path.dirname(os.path.abspath(__file__))

def json_loads_fast(data):
    try:
        return orjson.loads(data)
    except orjson.JSONDecodeError as e:
        if "number is infinity" in str(e):
            return json.loads(data)
        raise e

def load_traces(file_path):
    with open(file_path, 'rb') as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            out = []
            while line := mm.readline():
                out.append(Event.from_dict(json_loads_fast(line)))
            return out
        finally:
            mm.close()

def get_trace_dir(agent='gold'):
    # return os.path.join(DIR, f'../../../logs/run_evaluation/trace.debug.{agent}.{os.getuid()}/{agent}')
    return f"/home/yusuf/explainbench/shared_logs/logs/run_evaluation/trace.debug.{agent}.1020/{agent}"

def load_trace_pair(agent, instance_id, test_id=0, base_dir=None):
    # test_id refers to the index of FAIL_TO_PASS tests
    if base_dir is None:
        base_dir = get_trace_dir(agent)
    # print(base_dir)
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    diff_lines = get_diff_info_per_instance(base_dir, instance_id)
    buggy_path = os.path.join(base_dir, instance_id, f"buggy_traces/{test_name}.jsonl")
    patched_path = os.path.join(base_dir, instance_id, f"patched_traces/{test_name}.jsonl")
    buggy_traces = Traces(buggy_path, diff_lines.get('removed', {}))
    patched_traces = Traces(patched_path, diff_lines.get('added', {}))
    return buggy_traces, patched_traces

def diff_events(buggy: Event, patched: Event, repo_name, **kwargs):
    try:
        return DeepDiff(
            buggy.dump(),
            patched.dump(),
            cache_size=5000,
            significant_digits=3,
            ignore_order=False,                           
            ignore_order_func=get_ignore_order_func(repo_name),
            ignore_private_variables=False,
            **kwargs,
        )
    except TimeoutError as e:
        raise e
    except Exception as e:
        print(f"Error diffing events: {e}\nBuggy - at line {buggy.line_number} in {buggy.filepath}: {buggy.statement}\nPatched - at line {patched.line_number} in {patched.filepath}: {patched.statement}")
        return dict()

def rv_equals(rv1, rv2):
    diff = DeepDiff(rv1, rv2, significant_digits=5, ignore_private_variables=False)
    return diff == {}

class FunctionBlock:
    def __init__(self, id, name, parent, params=None, is_pmf=False):
        self.id = id             # type: int
        self.name = name         # type: str
        self.parent = parent     # type: FunctionBlock | None
        self.params = params
        self.is_pmf = is_pmf     # type: bool
        self.return_value = None # type: any | None
        self.exception = None    # type: tuple[str, str] | None
        self._events = []        # type: list[Event]
        self._links = {}         # type: dict[int, FunctionBlock]
        self._index = -1
        
    def add_event(self, event: Event):
        self._events.append(event)
    
    def step_into(self, event: FunctionEvent):
        assert isinstance(event, FunctionEvent), "Not a FunctionEvent"
        return self._links[event.event_id]
    
    def returns_equals(self, other):
        assert isinstance(other, FunctionBlock), "Not a FunctionBlock"
        match self.return_value, self.exception, other.return_value, other.exception:
            case rv1, None, rv2, None:
                return rv_equals(rv1, rv2)
            case None, e1, None, e2:
                return e1 == e2
            case (_, None, None, _) | (None, _, _, None):
                return False
            case _:
                raise ValueError("Exception and return value cannot coexist")
    
    @property
    def return_event(self):
        match self.return_value, self.exception:
            case _, None:
                assert len(self._events) >= 1 and isinstance(self._events[-1], ReturnEvent)
                return self._events[-1]
            case None, _:
                assert len(self._events) >= 2 and isinstance(self._events[-2], ExceptionEvent)
                return self._events[-2]
            case _:
                raise ValueError("Exception and return value cannot coexist")
    
    @property
    def return_type(self):
        return self.return_event.event_type
    
    def _init_index(self):
        if not self.is_pmf:
            return 0
        match self.return_value, self.exception:
            case _, None:
                assert len(self._events) >= 1 and isinstance(self._events[-1], ReturnEvent)
                return len(self._events) - 1
            case None, _:
                assert len(self._events) >= 2 and isinstance(self._events[-2], ExceptionEvent)
                return len(self._events) - 2
            case _:
                raise ValueError("Exception and return value cannot coexist")
    
    def _next_event(self):
        if self._index == -1:
            self._index = self._init_index()
        if self._index >= len(self._events):
            raise StopIteration
        event = self._events[self._index]
        self._index += 1
        return event

    def __iter__(self):
        return self
    
    def __next__(self) -> Event:
        event = self._next_event()
        while event.excluded and isinstance(event, LineEvent):
            event = self._next_event()
        return event

class Traces:
    def __init__(self, trace_path: str, diff_lines=None):
        self._entry = FunctionBlock(-1, "<module>", None)
        self._events = load_traces(trace_path)
        self._diff_lines = diff_lines or {} # type: dict[str, list[int]]
        self._pmf = self._patch_modified_functions()
        self._build_traces()

    def _build_traces(self):
        stack = [self._entry]
        for idx, e in enumerate(self._events):
            stack[-1].add_event(e)
            relpath = os.path.relpath(e.filepath, '/testbed')
            if e.line_number in self._diff_lines.get(relpath, []):
                e.excluded = True
            match e:
                case FunctionEvent():
                    is_pmf = e.function_name in self._pmf
                    new_block = FunctionBlock(e.event_id, e.function_name, stack[-1], params=e.parameters, is_pmf=is_pmf)
                    stack[-1]._links[e.event_id] = new_block
                    stack.append(new_block)
                case ReturnEvent():
                    stack[-1].return_value = e.return_value
                    if stack[-1].return_value is not None and stack[-1].exception is not None:
                        if stack[-1].exception[0] == "StopIteration":
                            stack[-1].exception = None
                    stack.pop()
                case ExceptionEvent():
                    ne = self._events[idx + 1] if idx + 1 < len(self._events) else None
                    if isinstance(ne, ReturnEvent):
                        stack[-1].exception = (e.exception_type, e.exception_value)
                case _: pass
    
    def _patch_modified_functions(self):
        if not self._diff_lines:
            return []
        modified_functions = set()
        for e in self._events:
            path, line = os.path.relpath(e.filepath, '/testbed'), e.line_number
            if line in self._diff_lines.get(path, []):
                modified_functions.add(e.function_name)
        return list(modified_functions)

    @property
    def entry(self):
        fbs = list(self._entry._links.values())
        assert len(fbs) > 0, "<module> does not call any test functions"
        return fbs[0]
