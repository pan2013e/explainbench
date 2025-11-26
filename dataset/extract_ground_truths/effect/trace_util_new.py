import sys
import json
from tracer.protocol import Event

def load_jsonl(file_path):
    events = []
    with open(file_path, 'r') as f:
        for line in f:
            event = Event.from_dict(json.loads(line))
            events.append(event)
    return events

class FunctionBlock:
    def __init__(self, id, name, parent, params=None):
        self.id = id
        self.name = name
        self.parent = parent
        self.params = params
        self.events = []
        self.links = {}
        self.return_value = None
        self.exception = None
        self.pointer = 0
        
    def add_event(self, event):
        self.events.append(event)
    
    def next_event(self):
        if self.pointer >= len(self.events):
            raise StopIteration
        event = self.events[self.pointer]
        self.pointer += 1
        return event

class Traces:
    def __init__(self, trace_path):
        self._entry = FunctionBlock(-1, "<module>", None)
        events = load_jsonl(trace_path)
        self._events_iterator = iter(events)
        self._build_traces()
    
    def _next_event(self):
        return next(self._events_iterator)
    
    def _build_traces_event(self, stack):
        try:
            e = self._next_event()
        except StopIteration:
            return None
        stack[-1].add_event(e)
        if e.event_type == "Function":
            new_block = FunctionBlock(e.event_id, e.function_name, stack[-1], params=e.parameters)
            stack[-1].links[e.event_id] = new_block
            stack.append(new_block)
        elif e.event_type == "Return":
            stack[-1].return_value = e.return_value
            stack.pop()
        elif e.event_type == "Exception":
            stack[-1].exception = (e.exception_type, e.exception_value)
        self._build_traces_event(stack)
    
    def _build_traces(self):
        sys.setrecursionlimit(10000)
        stack = [self._entry]
        self._build_traces_event(stack)
        sys.setrecursionlimit(1000)

    @property
    def entry(self):
        return list(self._entry.links.values())[0]