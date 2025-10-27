import json

from typing import Any, Dict, List, Optional
from deepdiff import DeepDiff
from tracer.protocol import Event, FunctionEvent, ReturnEvent

def load_traces(file_path):
    with open(file_path, 'r') as f:
        traces = [Event.from_dict(json.loads(line)) for line in f]
    return traces

def ignore_order_func(level):
    unordered_fields = ['vars_used', 'vars_defined']
    return any(field in level.path() for field in unordered_fields)

class FunctionBlock:
    def __init__(self, function_name: str, params: Dict[str, Any], caller: Optional['FunctionBlock']):
        self.events = [] # type: List[Event]
        self.function_name = function_name
        self.params = params
        self.caller = caller
    
    def call_chain(self):
        chain = []
        current = self
        while current:
            chain.append(current.function_name)
            current = current.caller
        return list(reversed(chain))
    
    def add_event(self, event: Event):
        self.events.append(event)
    
    def __iter__(self):
        for event in self.events:
            yield event

class Traces:
    def __init__(self, trace_file: str):
        self.events = load_traces(trace_file)
        self.blocks = [FunctionBlock('<module>', {}, None)]
        self._init(self.events)

    def _init(self, events: List[Event]):
        current_block = self.blocks[0]
        for event in events:
            if isinstance(event, FunctionEvent):
                block = FunctionBlock(event.function_name, event.parameters, current_block)
                self.blocks.append(block)
                current_block = block
                current_block.add_event(event)
            elif isinstance(event, ReturnEvent):
                current_block.add_event(event)
                caller = current_block.caller
                assert caller, "Return without caller"
                block = FunctionBlock(caller.function_name, caller.params, caller.caller)
                self.blocks.append(block)
                current_block = block
            else:
                current_block.add_event(event)
    
    def __iter__(self):
        for block in self.blocks:
            yield block

if __name__ == "__main__":
    buggy_traces = Traces("buggy.jsonl")
    patched_traces = Traces("fixed.jsonl")
    for buggy_block, patched_block in zip(buggy_traces, patched_traces):
        # Before the divergence point, the function call chain should be the same
        if buggy_block.function_name != patched_block.function_name:
            exit(0)
        for buggy_event, patched_event in zip(buggy_block, patched_block):
            # If code lines differ, stop comparing further for now
            if buggy_event.statement != patched_event.statement:
                exit(0)
            diff = DeepDiff(buggy_event.model_dump(), patched_event.model_dump(), significant_digits=3, ignore_order=False, ignore_order_func=ignore_order_func, exclude_paths=["root['line_number]"])
            if 'seen_variables' in diff.affected_root_keys:
                print('In function: ', patched_block.function_name)
                print(f'- {buggy_event.event_type:<10} {buggy_event.statement}')
                print(f'+ {patched_event.event_type:<10} {patched_event.statement}')
                print('Diff: ', diff)
                print('Diff dict: ', diff.to_dict())
                # assert patched_block.params == buggy_block.params, f"Function parameters differ, buggy: {buggy_block.params}, patched: {patched_block.params}"
                print('Function parameters: ', patched_block.params)
                if hasattr(patched_event, 'seen_variables'):
                    print('Buggy Variables: ', buggy_event.seen_variables)
                    print('====')
                    print('Variables: ', patched_event.seen_variables)
                input('===')
