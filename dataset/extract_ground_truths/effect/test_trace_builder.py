import traceback
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional, List
from dataset.extract_ground_truths.effect.trace_util import TraceBuilder


@dataclass
class BaseEvent:
    event_id: int
    event_type: str
    caller_name: Optional[str]
    filepath: Optional[str]
    function_name: Optional[str]
    line_number: Optional[int] = None
    statement: Optional[str] = None
    vars_used: Optional[Dict[str, Any]] = None
    vars_defined: Optional[Dict[str, Any]] = None
    seen_variables: Optional[Dict[str, Any]] = None
    control_dependencies: Optional[Dict[str, Any]] = None
    inherited_control_dependencies: Optional[Dict[str, Any]] = None
    parameters: Optional[Dict[str, Any]] = None
    parameter_sources: Optional[Dict[str, Any]] = None
    return_value: Any = None
    exception_type: Optional[str] = None
    exception_value: Optional[str] = None

class FunctionEvent(BaseEvent):
    def __init__(self, event_id, caller_name, filepath, function_name, parameters=None, parameter_sources=None):
        super().__init__(
            event_id=event_id,
            event_type="Function",
            caller_name=caller_name,
            filepath=filepath,
            function_name=function_name,
            parameters=parameters or {},
            parameter_sources=parameter_sources or {},
        )

class LineEvent(BaseEvent):
    def __init__(self, event_id, filepath, function_name, line_number, statement="pass"):
        super().__init__(
            event_id=event_id,
            event_type="Line",
            caller_name=None,
            filepath=filepath,
            function_name=function_name,
            line_number=line_number,
            statement=statement,
        )

class ReturnEvent(BaseEvent):
    def __init__(self, event_id, filepath, function_name, return_value=None):
        super().__init__(
            event_id=event_id,
            event_type="Return",
            caller_name=None,
            filepath=filepath,
            function_name=function_name,
            return_value=return_value,
        )

class ExceptionEvent(BaseEvent):
    def __init__(self, event_id, filepath, function_name, exception_type="ValueError", exception_value="boom"):
        super().__init__(
            event_id=event_id,
            event_type="Exception",
            caller_name=None,
            filepath=filepath,
            function_name=function_name,
            exception_type=exception_type,
            exception_value=exception_value,
        )


FP = "/app/main.py"

def build(events: List[BaseEvent]):
    builder = TraceBuilder(root_function_name="<module>")
    return builder.build(events)


def test_T1_single_call_lines_return():
    ev = [
        FunctionEvent(1, caller_name="<module>", filepath=FP, function_name="foo", parameters={"x": 1}),
        LineEvent(2, filepath=FP, function_name="foo", line_number=10),
        LineEvent(3, filepath=FP, function_name="foo", line_number=11),
        ReturnEvent(4, filepath=FP, function_name="foo", return_value=42),
    ]

    tr = TraceBuilder().build(ev)
    roots = tr.roots
    assert len(roots) == 1

    root = roots[0]
    assert len(root.children) == 1

    foo = root.children[0]
    assert foo.function_name == "foo"
    assert foo.return_event is not None
    assert foo.status == "returned"

    assert tr.func_index[(FP, "foo")] == [foo.scope_id]
    for e in ev:
        assert e.event_id in tr.event_to_scope
        assert tr.event_to_scope[e.event_id] == foo.scope_id or tr.event_to_scope[e.event_id] == root.scope_id


def test_T2_nested_calls():
    ev = [
        FunctionEvent(1, "<module>", FP, "main"),
        LineEvent(2, FP, "main", 5),
        FunctionEvent(3, "main", FP, "bar"),
        LineEvent(4, FP, "bar", 20),
        ReturnEvent(5, FP, "bar", return_value="ok"),
        LineEvent(6, FP, "main", 6),
        ReturnEvent(7, FP, "main", return_value=0),
    ]

    tr = TraceBuilder().build(ev)

    root = tr.roots[0]
    main = root.children[0]
    bar = main.children[0]

    assert main.function_name == "main" and bar.function_name == "bar"
    assert main.depth == 1 and bar.depth == 2
    assert bar.status == "returned" and main.status == "returned"
    assert bar.end_event_id == 5 and main.end_event_id == 7
    assert tr.func_index[(FP, "main")] == [main.scope_id]
    assert tr.func_index[(FP, "bar")] == [bar.scope_id]


def test_T3_recursion_two_invocations():
    ev = [
        FunctionEvent(1, "<module>", FP, "f"),
        FunctionEvent(2, "f", FP, "f"),
        ReturnEvent(3, FP, "f", return_value=1),  # closes inner
        ReturnEvent(4, FP, "f", return_value=2),  # closes outer
    ]

    tr = TraceBuilder().build(ev)

    root = tr.roots[0]
    outer = root.children[0]
    inner = outer.children[0]

    assert outer.function_name == inner.function_name == "f"
    calls = tr.func_index[(FP, "f")]
    assert len(calls) == 2
    assert set(calls) == {outer.scope_id, inner.scope_id}
    assert inner.end_event_id == 3
    assert outer.end_event_id == 4


def test_T4_exception_closes_scope():
    ev = [
        FunctionEvent(1, "<module>", FP, "f"),
        LineEvent(2, FP, "f", 100),
        ExceptionEvent(3, FP, "f", exception_type="ZeroDivisionError", exception_value="division by zero"),
    ]

    tr = TraceBuilder().build(ev)

    f = tr.roots[0].children[0]
    assert f.status == "exception"
    assert f.exception_event is not None
    assert f.return_event is None
    assert f.end_event_id == 3


def test_T5_incomplete_scope_at_end():
    ev = [
        FunctionEvent(1, "<module>", FP, "f"),
        LineEvent(2, FP, "f", 123),
    ]

    tr = TraceBuilder().build(ev)

    f = tr.roots[0].children[0]
    assert f.status == "incomplete"
    assert f.end_event_id == 2

def run(test_fn):
    name = test_fn.__name__
    try:
        test_fn()
        print(f"[PASS] {name}")
        return True
    except AssertionError as ae:
        print(f"[FAIL] {name}: AssertionError: {ae}")
        traceback.print_exc()
        return False
    except Exception as ex:
        print(f"[ERROR] {name}: {ex}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_T1_single_call_lines_return,
        test_T2_nested_calls,
        test_T3_recursion_two_invocations,
        test_T4_exception_closes_scope,
        test_T5_incomplete_scope_at_end,
    ]
    results = [run(t) for t in tests]
    passed = sum(results)
    total = len(results)
    print(f"\nSummary: {passed}/{total} tests passed.")
    sys.exit(0 if passed == total else 1)