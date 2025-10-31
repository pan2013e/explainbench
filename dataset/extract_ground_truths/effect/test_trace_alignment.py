from dataclasses import dataclass
from typing import Optional
from dataset.extract_ground_truths.effect.trace_util import align_function_calls_greedy, TraceBuilder

@dataclass
class FunctionEvent:
    event_id: int
    filepath: Optional[str]
    function_name: str
    caller_name: Optional[str]
    line_number: Optional[int] = None
    statement: Optional[str] = None
    parameters: Optional[dict] = None
    parameter_sources: Optional[dict] = None

@dataclass
class ReturnEvent:
    event_id: int
    filepath: Optional[str]
    function_name: str
    line_number: Optional[int] = None
    statement: Optional[str] = None
    return_value: Optional[object] = None

def _pairs_to_names(result, buggy_tr, patched_tr):
    out = []
    for b, p in result.ordered_pairs:
        bname = buggy_tr.scopes[b].function_name if b is not None else None
        pname = patched_tr.scopes[p].function_name if p is not None else None
        out.append((bname, pname))
    return out

def _ids_by_name(tr, target_name):
    return [sid for sid, s in tr.scopes.items() if s.function_name == target_name and s.call_event and s.call_event.event_id != -1]

def build_buggy_events():
    # Buggy:
    # 1: f1(); 2: g(); 3: ret g; 4: g(); 5: ret g; 6: ret f1; 7: h(); 8: ret h
    ev = []
    eid = 1
    ev.append(FunctionEvent(eid, "app.py", "f1", "<module>")); eid += 1
    ev.append(FunctionEvent(eid, "app.py", "g",  "f1"));       eid += 1
    ev.append(ReturnEvent(  eid, "app.py", "g"));               eid += 1
    ev.append(FunctionEvent(eid, "app.py", "g",  "f1"));       eid += 1
    ev.append(ReturnEvent(  eid, "app.py", "g"));               eid += 1
    ev.append(ReturnEvent(  eid, "app.py", "f1"));              eid += 1
    ev.append(FunctionEvent(eid, "app.py", "h",  "<module>"));  eid += 1
    ev.append(ReturnEvent(  eid, "app.py", "h"));               eid += 1
    return ev

def build_patched_events():
    # Patched:
    # 1: z(); 2: ret z; 3: f1(); 4: g(); 5: ret g; 6: w(); 7: g() [caller=w]; 8: ret g; 9: ret w; 10: ret f1
    ev = []
    eid = 1
    ev.append(FunctionEvent(eid, "app.py", "z",  "<module>"));  eid += 1
    ev.append(ReturnEvent(  eid, "app.py", "z"));               eid += 1
    ev.append(FunctionEvent(eid, "app.py", "f1", "<module>"));  eid += 1
    ev.append(FunctionEvent(eid, "app.py", "g",  "f1"));        eid += 1
    ev.append(ReturnEvent(  eid, "app.py", "g"));               eid += 1
    ev.append(FunctionEvent(eid, "app.py", "w",  "f1"));        eid += 1
    ev.append(FunctionEvent(eid, "app.py", "g",  "w"));         eid += 1
    ev.append(ReturnEvent(  eid, "app.py", "g"));               eid += 1
    ev.append(ReturnEvent(  eid, "app.py", "w"));               eid += 1
    ev.append(ReturnEvent(  eid, "app.py", "f1"));              eid += 1
    return ev

def run_test():
    # Build trace representations
    buggy_events = build_buggy_events()
    patched_events = build_patched_events()

    tb = TraceBuilder()
    buggy_tr = tb.build(buggy_events)
    tb2 = TraceBuilder()
    patched_tr = tb2.build(patched_events)

    # Align
    result = align_function_calls_greedy(buggy_tr, patched_tr)

    # Validate structure & invariants
    # validate_function_alignment(result, buggy_tr, patched_tr)

    # Expected ordered name pairs
    expected = [
        (None,  "z"),   # added before first anchor
        ("f1",  "f1"),  # matched
        ("g",   "g"),   # first g (caller f1)
        (None,  "w"),   # added between anchors
        ("g",   "g"),   # second g (caller changed to w)
        ("h",   None),  # removed
    ]

    got = _pairs_to_names(result, buggy_tr, patched_tr)
    assert len(got) == len(expected), f"length mismatch: {len(got)} vs {len(expected)}"
    assert got == expected, f"\nExpected:\n{expected}\nGot:\n{got}"

    # Check counts
    assert len(result.matched_pairs) == 3, f"expected 3 matches, got {len(result.matched_pairs)}"

    # Removed-only (buggy): should be exactly 'h'
    removed_names = sorted({buggy_tr.scopes[b].function_name for b in result.removed_bug_scope_ids})
    assert removed_names == ["h"], f"removed mismatch: {removed_names}"

    # Added-only (patched): should be exactly 'w' and 'z'
    added_names = sorted({patched_tr.scopes[p].function_name for p in result.added_pat_scope_ids})
    assert added_names == ["w", "z"], f"added mismatch: {added_names}"

    # If all good, print a short summary
    print("function-level alignment test passed.")
    try:
        from pprint import pprint
        print("\nOrdered pairs (names):")
        pprint(got)
    except Exception:
        pass

if __name__ == "__main__":
    run_test()