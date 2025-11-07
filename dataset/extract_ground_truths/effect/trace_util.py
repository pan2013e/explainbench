import json
import os

from typing import Any, Dict, List, Literal, Optional, Tuple

from deepdiff import DeepDiff
from tracer.protocol import Event, FunctionEvent, ReturnEvent
from dataset.extract_ground_truths.effect.diff_util import sequence_match
from dataset.extract_ground_truths.effect.postprocessing_util import get_ignore_order_func

def load_traces(file_path):
    with open(file_path, 'r') as f:
        traces = [Event.from_dict(json.loads(line)) for line in f]
    return traces

class FunctionBlock:
    def __init__(self, file_path: str, function_name: str, params: Dict[str, Any], trace_type: Literal['buggy', 'patched'], caller: Optional['FunctionBlock']):
        self.events = [] # type: List[Event]
        self.file_path = os.path.relpath(file_path, '/testbed')
        self.function_name = function_name
        self.params = params
        self.trace_type = trace_type
        self.caller = caller
    
    def add_event(self, event: Event):
        self.events.append(event)
    
    def get_patch_modified_lines(self, diff_lines: Dict[str, List[int]]):
        key = 'added' if self.trace_type == 'patched' else 'removed'
        if self.file_path not in diff_lines[key]:
            return []
        existing_linenos = list(set(event.line_number for event in self.events))
        return [lineno for lineno in diff_lines[key][self.file_path] if lineno in existing_linenos]
    
    def is_function_excluded(self):
        return all(event.excluded for event in self.events)
    
    def __iter__(self):
        for event in self.events:
            if event.excluded:
                continue
            yield event

class Traces:
    def __init__(self, trace_file: str, diff_lines: Dict[str, List[int]], trace_type: Literal['buggy', 'patched']):
        self.trace_type = trace_type
        self.events = load_traces(trace_file)
        self.blocks = [FunctionBlock('<module>', '<test>', {}, self.trace_type, None)]
        self.callsites = [] # type: List[Tuple[Event, FunctionBlock]]
        self._init(self.events, diff_lines)

    def _init(self, events: List[Event], diff_lines: Dict[str, List[int]]):
        current_block = self.blocks[0]
        for idx, event in enumerate(events):
            if isinstance(event, FunctionEvent):
                block = FunctionBlock(event.filepath, event.function_name, event.parameters, self.trace_type, current_block)
                self.blocks.append(block)
                # Record call sites (except the test function call)
                if current_block is not self.blocks[0]:
                    self.callsites.append((self.events[idx - 1], block))
                current_block = block
                current_block.add_event(event)
            elif isinstance(event, ReturnEvent):
                current_block.add_event(event)
                caller = current_block.caller
                assert caller, "Return without caller"
                block = FunctionBlock(event.filepath, caller.function_name, caller.params, caller.trace_type, caller.caller)
                self.blocks.append(block)
                current_block = block
            else:
                current_block.add_event(event)
        self._exclude_lines(diff_lines)
        self._merge_blocks()
    
    def _exclude_event(self, event: Event):
        '''
        Mark the event as excluded. If the event calls a function, exclude all events in the callee as well. Since this is recursive, all callees along the call chain are excluded.
        '''
        event.excluded = True
        for e, fb in self.callsites:
            if e == event:
                # Use original list instead of __iter__ to avoid modification during iteration
                for fb_event in fb.events:
                    self._exclude_event(fb_event)
                break
    
    def _exclude_lines(self, diff_lines: Dict[str, List[int]]):
        '''
        Get overlapping line numbers from `diff_lines` for each block, and exclude corresponding events.
        '''
        for block in self.blocks[1:]:
            modified_lines = block.get_patch_modified_lines(diff_lines)
            if not modified_lines:
                continue
            related_events = [event for event in block.events if event.line_number in modified_lines]
            for event in related_events:
                self._exclude_event(event)
    
    def _merge_blocks(self):
        '''
        After excluding events, some function blocks may be entirely excluded. So we need to merge "consecutive" unexcluded blocks of the same function into one.
        '''
        if len(self.blocks) <= 2:
            return
        block_to_remove = []
        cur_func_name = self.blocks[1].function_name
        cur_block = self.blocks[1]
        for block in self.blocks[2:]:
            if block.is_function_excluded():
                continue
            if block.function_name == cur_func_name:
                cur_block.events.extend(block.events)
                block_to_remove.append(block)
            else:
                cur_func_name = block.function_name
                cur_block = block
        for block in block_to_remove:
            self.blocks.remove(block)
    
    def __iter__(self):
        for block in self.blocks:
            if block.is_function_excluded():
                continue
            yield block

def function_match(buggy_traces: Traces, patched_traces: Traces):
    buggy_blocks = [block for block in buggy_traces]
    patched_blocks = [block for block in patched_traces]
    idx_pairs = sequence_match(
        buggy_blocks, patched_blocks,
        key=lambda block: block.function_name
    )
    print(idx_pairs)
    pairs = [(buggy_blocks[i], patched_blocks[j]) for i, j in idx_pairs]
    return pairs  

def event_match(buggy_block: FunctionBlock, patched_block: FunctionBlock):
    buggy_events = [event for event in buggy_block]
    patched_events = [event for event in patched_block]
    idx_pairs = sequence_match(
        buggy_events, patched_events,
        key=lambda event: event.statement
    )
    pairs = [(buggy_events[i], patched_events[j]) for i, j in idx_pairs]
    return pairs

def diff_events(buggy: Event, patched: Event, repo_name, **kwargs):
    return DeepDiff(
        buggy.dump(),
        patched.dump(),
        significant_digits=3,
        ignore_order=False,                           
        ignore_order_func=get_ignore_order_func(repo_name),
        ignore_private_variables=False,
        # exclude_paths=["root['seen_variables']['transform']"],
        **kwargs,
    )