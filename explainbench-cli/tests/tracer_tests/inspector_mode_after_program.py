# NOTE: To make line numbers consistent, only append new test code before `if __name__ == "__main__":`
import os
import traceback

from tracer import ExpressionInspector as Inspector
from tracer.protocol import InspectionResult as Result

FILE_PATH = os.path.abspath(__file__)

def assert_equals(obj, expected):
    assert obj == expected, f"Provided: {obj}\nExpected: {expected}"

def test_basic_function():
    def func():
        a = 10
        b = 20
        c = a + b
        return c
    with Inspector(FILE_PATH, 17, 'c', mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 30)

def test_function_with_exception_handled():
    def func():
        a = 10
        b = 20
        try:
            assert False, "Intentional Failure"
        except AssertionError:
            b = 30
        c = a + b
        return c
    with Inspector(FILE_PATH, 32, 'c', mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 40)
    with Inspector(FILE_PATH, 31, 'b', mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.exception[0], None)
    assert_equals(result.value[0], 30)

def test_function_with_exception_unhandled_before_inspection():
    def func():
        a = 10
        b = 20
        assert False, "Intentional Failure"
        c = a + b
        return c
    with Inspector(FILE_PATH, 49, 'c', mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value, None)
    assert_equals(result.exception.stage, 'exception before breakpoint')
    assert_equals(result.exception.type, 'AssertionError')

def test_more_complex_expr1():
    def func():
        a = [1, 2, 3]
        b = [4, 5, 6]
        c = a + b
        return c
    with Inspector(FILE_PATH, 62, 'len(c)', mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 6)
    with Inspector(FILE_PATH, 62, 'c[3]', mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 4)

def test_variable_scope():
    def func1():
        a = 10
        def inner():
            b = 20
            return a + b
        c = inner()
        return c
    with Inspector(FILE_PATH, 79, 'b', mode='after') as inspector:
        func1()
    result = Result(**inspector.result)
    assert_equals(result.value[0], None)
    assert_equals(result.exception[0].type, 'NameError')
    with Inspector(FILE_PATH, 77, 'a', mode='after') as inspector:
        func1()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 10)
    
    def func2():
        a = 10
        if True:
            b = 20
        c = a + b
        return c
    with Inspector(FILE_PATH, 95, 'b', mode='after') as inspector:
        func2()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 20)

def test_count_parameter():
    def func():
        x = 0
        for i in range(5):
            x = i + 1
        return x
    with Inspector(FILE_PATH, 106, 'x', count=3, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 3)

def test_more_complex_expr2():
    def func():
        class MyClass:
            def __init__(self, val):
                self.val = val
            def get_val(self):
                return self.val
        obj = MyClass(42)
        return obj
    with Inspector(FILE_PATH, 120, 'obj.get_val()', mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 42)

def test_library_call():
    import numpy as np
    def func():
        a = np.array([1, 2, 3])
        b = np.array([4, 5, 6])
        c = a + b
        return c
    with Inspector(FILE_PATH, 132, 'c.tolist()', mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], [5, 7, 9])
    with Inspector(FILE_PATH, 132, 'int(np.sum(c))', mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 21)

def test_return_inspection():
    def func():
        a = 5
        b = 10
        return a * b
    with Inspector(FILE_PATH, 147, '__return__', count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 50)
    with Inspector(FILE_PATH, 147, '__return__ * 2', count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 100)

def test_function_call_in_return():
    def helper(x):
        return x + 1
    def func():
        a = 5
        return helper(a)
    with Inspector(FILE_PATH, 162, '__return__', count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 6)
    with Inspector(FILE_PATH, 162, 'helper(__return__)', count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 7)
    with Inspector(FILE_PATH, 159, '__return__', count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 6)

def test_nested_call_in_return():
    def helper1(x):
        return x + 2
    def helper2(y):
        return helper1(y) * 3
    def func():
        a = 4
        return helper2(a)
    with Inspector(FILE_PATH, 183, '__return__', count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], 18)

def test_func_returning_none_implicitly():
    def func():
        pass
    with Inspector(FILE_PATH, 191, '__return__', count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], None)

def test_function_with_exception_unhandled_at_inspection():
    def func():
        x = 10
        y = 0
        return x/y
    with Inspector(FILE_PATH, 201, '__return__', count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], ['ZeroDivisionError', 'division by zero'])
    with Inspector(FILE_PATH, 201, '__exception__', count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value[0], ['ZeroDivisionError', 'division by zero'])

def test_multiple_exprs():
    def func():
        a = 3
        b = 4
        c = a * b
        return c
    with Inspector(FILE_PATH, 215, ['a', 'b', 'c'], mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(result.value, [3, 4, 12])

def test_call_in_return_that_changes_variable():
    def helper(x):
        x['key'] = 5
        return x
    def func():
        a = {}
        return helper(a)
    with Inspector(FILE_PATH, 228, ['a', '__return__'], count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    # Inspection of __return__ is after the execution of line 228 regardless of mode,
    # and 'a' is inspected after the execution in 'after' mode.
    # So putting 'a' and '__return__' together is compatible in 'after' mode
    # We accept this kind of expr list in 'after' mode
    assert_equals(result.value, [{"key": 5}, {'key': 5}])
    assert_equals(result.exception[0], None)

def test_inspect_return_at_wrong_line():
    def func():
        a = 5
        b = 10
        return a * b
    with Inspector(FILE_PATH, 242, ['a', '__return__'], count=2, mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    # No return event at line 242, so the debugger does not stop
    # Line 242 is never reached later
    assert_equals(result.value, None)
    assert_equals(result.exception.stage, 'not reached')

def test_multi_expr_with_encoded_string():
    from tracer.inspector import encode_expr_list
    def func():
        a = 7
        b = 8
        c = a + b
        return c
    with Inspector(FILE_PATH, 257, encode_expr_list(["a", "b", "c"]), mode='after') as inspector:
        func()
    result = Result(**inspector.result)
    assert_equals(inspector.expr, ["a", "b", "c"])
    assert_equals(result.value, [7, 8, 15])

if __name__ == "__main__":
    test_funcs = [obj for name, obj in globals().items() if name.startswith('test_') and callable(obj)]
    for test_func in test_funcs:
        try:
            test_func()
            print(f"{test_func.__name__}: PASS")
        except Exception as e:
            print(f"{test_func.__name__}: FAIL")
            print(f'==== {test_func.__name__} ====')
            traceback.print_exc()
            print('=======================')