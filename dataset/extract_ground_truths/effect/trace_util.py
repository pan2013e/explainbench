import json
import os
import re
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional, Tuple

from deepdiff import DeepDiff
from tracer.protocol import Event, FunctionEvent, ReturnEvent
from dataset.extract_ground_truths.effect.diff_util import sequence_match
from postprocessing_util import get_ignore_order_func

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

_BRACKETED_NAME_RE = re.compile(r"\[['\"]([^'\"]+)['\"]\]")
_VAR_NAME_INDEX = 1

def extract_var_name(full_path: str) -> str:
    tokens = _BRACKETED_NAME_RE.findall(str(full_path))
    if len(tokens) > _VAR_NAME_INDEX:
        return tokens[_VAR_NAME_INDEX]
    return ""  # safe fallback

def iter_diff_items(diffs_by_kind: Dict[str, Any]) -> Iterator[Tuple[str, str, Any]]:
    for change_kind, changes_for_kind in (diffs_by_kind or {}).items():
        if isinstance(changes_for_kind, dict):
            for full_path, payload in changes_for_kind.items():
                yield change_kind, full_path, payload
        elif isinstance(changes_for_kind, list):
            for payload in changes_for_kind:
                yield change_kind, payload, payload

def count_changed_vars(diffs_by_kind: Dict[str, Any]) -> int:
    n_var = 0
    for _ in iter_diff_items(diffs_by_kind):
        n_var += 1
    return n_var

def _filter_by_predicate(
    diff_dict: Dict[str, Any],
    keep: Callable[[str, str, Any], bool]
) -> Dict[str, Any]:
    """Return a new diffs-by-kind dict keeping only entries where keep(kind, path, payload) is True."""
    if not diff_dict:
        return {}
    out: Dict[str, Any] = {}
    for change_key, change_val in diff_dict.items():
        if isinstance(change_val, dict):
            kept = {}
            for full_path, payload in change_val.items():
                if keep(change_key, full_path, payload):
                    kept[full_path] = payload
            if kept:
                out[change_key] = kept
        elif isinstance(change_val, list):
            kept_list = []
            for payload in change_val:
                path_like = str(payload)
                if keep(change_key, path_like, payload):
                    kept_list.append(payload)
            if kept_list:
                out[change_key] = kept_list
    return out

def filter_added_dict_based_on_seen_variables(diff_dict: Dict[str, Any], event) -> Dict[str, Any]:
    """
    only process 'dictionary_item_added' entries; keep other change_key unchanged.
    Keep added entries whose var is NOT in event.seen_variables.
    """
    if not diff_dict:
        return {}
    seen = getattr(event, "seen_variables", {}) or {}

    def keep(kind: str, path: str, payload: Any) -> bool:
        if kind != "dictionary_item_added":
            return True  # preserve non-addition kinds
        var_name = extract_var_name(path)
        # keep only if var NOT already seen
        return var_name and (var_name not in seen)

    return _filter_by_predicate(diff_dict, keep)

def filter_based_on_vars_at_current_line(diff_dict: Dict[str, Any], event) -> Dict[str, Any]:
    """
    Keep entries whose var is referenced on the current line:
    referenced_vars = vars_used ∪ vars_defined
    """
    referenced = set(getattr(event, "vars_used", []) or []) | set(getattr(event, "vars_defined", []) or [])
    if not referenced:
        return diff_dict

    def keep(kind: str, path: str, payload: Any) -> bool:
        var_name = extract_var_name(path)
        return var_name in referenced

    return _filter_by_predicate(diff_dict, keep)

def filter_based_on_used_vars(diff_dict: Dict[str, Any], event) -> Dict[str, Any]:
    """Keep entries whose var is in event.vars_used."""
    used = set(getattr(event, "vars_used", []) or [])
    if not used:
        return {}

    def keep(kind: str, path: str, payload: Any) -> bool:
        var_name = extract_var_name(path)
        return var_name in used

    return _filter_by_predicate(diff_dict, keep)

def filter_based_on_type_changes(diff_dict: Dict[str, Any], event) -> Dict[str, Any]:
    """
    Last resort: if >1 changes remain and 'type_changes' exists, keep ONLY 'type_changes'.
    Otherwise return input unchanged.
    """
    if count_changed_vars(diff_dict) > 1 and "type_changes" in diff_dict:
        return {"type_changes": diff_dict["type_changes"]}
    return diff_dict

def apply_trace_filters(diffs_by_kind: Dict[str, Any], event) -> Dict[str, Any]:
    """
    Pipeline:
      1) filter_added_dict_based_on_seen_variables
      2) if empty OR <=1 change -> return
      3) filter_based_on_vars_at_current_line
      4) if <=1 change -> return
      5) filter_based_on_used_vars
      6) last-resort: type_changes only if still >1 changes and key exists
    Always returns a dict (possibly empty).
    Focus is LineEvent; if event lacks expected fields, gracefully degrades to {}.
    """
    if not diffs_by_kind:
        return {}

    # Step 1
    step1 = filter_added_dict_based_on_seen_variables(diffs_by_kind, event)
    n1 = count_changed_vars(step1)
    if n1 <= 1:
        return step1 or {}

    # Step 3
    step3 = filter_based_on_vars_at_current_line(step1, event)
    n3 = count_changed_vars(step3)
    if n3 <= 1:
        return step3 or {}

    # Step 5
    step5 = filter_based_on_used_vars(step3, event)
    n5 = count_changed_vars(step5)
    if n5 <= 1:
        return step5 or {}

    return filter_based_on_type_changes(step5, event)