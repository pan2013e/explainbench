from tracer import ExecutionTracer
from pathlib import Path
import json

def test_simple_if(x):
    if x > 0:
        result = "positive"
    return result

def test_if_else(x):
    if x > 0:
        label = "positive"
    else:
        label = "non-positive"
    return label

def test_nested_if(x, y):
    if x > 0:
        if y > 0:
            msg = "both positive"
        else:
            msg = "x positive, y not"
    else:
        msg = "x not positive"
    return msg

def helper(value):
    if value == "special":
        flag = True
    else:
        flag = False
    return flag


def main_controller(x):
    if x > 10:
        outcome = helper("special")
    else:
        outcome = helper("normal")
    return outcome

def leaf(a):
    return a * 2

def middle(b):
    temp = leaf(b + 1)
    return temp - 1

def root(c):
    result = middle(c * 3)
    return result + 10

def processor(item):
    if item % 2 == 0:
        status = "even"
    else:
        status = "odd"
    return status

def run_loop(values):
    results = []
    for val in values:
        res = processor(val)
        results.append(res)
    return results

def test_try_except_finally(x):
    result = None
    try:
        if x == 0:
            raise ValueError()
        result = 100 / x
    except ValueError as e:
        result = f"ValueError: {str(e)}"
    except ZeroDivisionError:
        result = "Division by zero"
    finally:
        if result is None:
            result = "Unknown error occurred"
    return result

def test_while_loop(start):
    counter = start
    results = []
    while counter > 0:
        results.append(counter)
        counter -= 1
    return results

def risky_function(x):
    if x < 0:
        raise RuntimeError(f"Negative value not allowed: {x}")
    return x ** 2

def wrapper(a):
    try:
        return risky_function(a)
    except RuntimeError as e:
        return f"Handled: {str(e)}"


def top_level():
    results = []
    inputs = [2, -1, 3]
    for val in inputs:
        res = wrapper(val)
        results.append(res)
    return results

class SimpleClass:
    def classify(self, x):
        if x > 0:
            category = "positive"
        else:
            category = "non-positive"
        return category


def test_class_method():
    obj = SimpleClass()
    return obj.classify(5)

def assert_events_equal(ground_truth_event, actual_event, event_id):
    """
    Assert that two trace events are equal, field by field.
    For list fields (except control_dependencies and inherited_control_dependencies):
      - Convert all elements to string
      - Sort lexicographically
    Handles dicts recursively.
    """
    fields_to_check = [
        "event_type",
        # "line_number",
        "statement",
        "filepath",
        # "function_name",
        # "caller_name",
        "return_value",
        "parameters",
        "parameter_sources",
        "vars_defined",
        "vars_used",
        "control_dependencies",
        "inherited_control_dependencies",
        "seen_variables",
    ]

    for field in fields_to_check:
        gt_val = ground_truth_event.get(field)
        act_val = actual_event.get(field)

        # Skip if both are None (optional fields)
        if gt_val is None and act_val is None:
            continue

        # Type check
        assert type(gt_val) == type(act_val), (
            f"Event {event_id}, field '{field}': type mismatch. "
            f"GT: {type(gt_val)}, Actual: {type(act_val)}"
        )

        # Handle lists — sort after converting to string, unless control-related
        if isinstance(gt_val, list):
            assert len(gt_val) == len(act_val), (
                f"Event {event_id}, field '{field}': length mismatch. "
                f"GT: {len(gt_val)}, Actual: {len(act_val)}"
            )

            if field not in ["control_dependencies", "inherited_control_dependencies"]:
                # Convert all elements to string, then sort
                gt_sorted = sorted(str(x) for x in gt_val)
                act_sorted = sorted(str(x) for x in act_val)
            else:
                # Preserve order for control dependencies
                gt_sorted = gt_val
                act_sorted = act_val

            for i, (gt_item, act_item) in enumerate(zip(gt_sorted, act_sorted)):
                # Compare as strings for sortable fields
                if field not in ["control_dependencies", "inherited_control_dependencies"]:
                    gt_str = str(gt_item)
                    act_str = str(act_item)
                    assert gt_str == act_str, (
                        f"Event {event_id}, field '{field}[{i}]': "
                        f"GT: {gt_str}, Actual: {act_str}"
                    )
                else:
                    # Compare original values for control dependencies
                    assert gt_item == act_item, (
                        f"Event {event_id}, field '{field}[{i}]': "
                        f"GT: {gt_item}, Actual: {act_item}"
                    )

        # Handle dicts
        elif isinstance(gt_val, dict):
            assert set(gt_val.keys()) == set(act_val.keys()), (
                f"Event {event_id}, field '{field}': keys mismatch. "
                f"GT: {set(gt_val.keys())}, Actual: {set(act_val.keys())}"
            )
            for key in gt_val:
                gt_item = gt_val[key]
                act_item = act_val[key]

                # If value is a list (and not inside control field — which it won’t be in seen_variables),
                # convert to string and sort before comparing
                if isinstance(gt_item, list):
                    gt_sorted = sorted(str(x) for x in gt_item)
                    act_sorted = sorted(str(x) for x in act_item)
                    assert gt_sorted == act_sorted, (
                        f"Event {event_id}, field '{field}[{key}]': sorted string mismatch. "
                        f"GT: {gt_sorted}, Actual: {act_sorted}"
                    )
                else:
                    assert gt_item == act_item, (
                        f"Event {event_id}, field '{field}[{key}]': "
                        f"GT: {gt_item}, Actual: {act_item}"
                    )

        # Handle primitives
        else:
            # Convert to string for comparison? Only if you want string-based equality.
            # But for primitives like int/bool/str, direct == is usually fine.
            # Let's keep original comparison unless you specify otherwise.
            assert gt_val == act_val, (
                f"Event {event_id}, field '{field}': "
                f"GT: {gt_val}, Actual: {act_val}"
            )

def validate_traces_against_ground_truth(ground_truth_dir, actual_traces_dir=None):
    """
    Load all ground truth trace files and compare against actual traces.
    If actual_traces_dir is None, you can plug in your own trace loader later.
    """
    ground_truth_path = Path(ground_truth_dir)

    for gt_file in ground_truth_path.glob("*.jsonl"):
        print(f"\nValidating: {gt_file.name}")

        # TODO: You need to map ground truth file to actual trace file
        # For now, assume actual trace file has same name in actual_traces_dir
        if actual_traces_dir:
            actual_file = Path(actual_traces_dir) / gt_file.name
            if not actual_file.exists():
                raise FileNotFoundError(f"Actual trace not found: {actual_file}")
        else:
            # ⚠️ PLACEHOLDER: Later, you'll load actual trace from memory or another source
            # For demo, we'll just re-use ground truth as "actual" to show it works
            actual_file = gt_file

        with open(gt_file, 'r') as gt_f, open(actual_file, 'r') as act_f:
            gt_lines = gt_f.readlines()
            act_lines = act_f.readlines()

            assert len(gt_lines) == len(act_lines), (
                f"Mismatch in number of events in {gt_file.name}: "
                f"GT: {len(gt_lines)}, Actual: {len(act_lines)}"
            )

            for i, (gt_line, act_line) in enumerate(zip(gt_lines, act_lines)):
                gt_event = json.loads(gt_line.strip())
                act_event = json.loads(act_line.strip())

                assert_events_equal(gt_event, act_event, i)

        print(f"✅ {gt_file.name} passed all assertions.")


if __name__ == "__main__":
    RESULTS_DIR = Path("results")
    RESULTS_DIR.mkdir(exist_ok=True)

    # Test test_simple_if
    tracer = ExecutionTracer(output_file="results/trace_test_simple_if_1.jsonl")
    tracer.start_tracing()
    try:
        test_simple_if(5)  # x > 0 → "positive"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_simple_if_2.jsonl")
    tracer.start_tracing()
    try:
        test_simple_if(-3)  # x <= 0 → UnboundLocalError (to expose missing else)
    except Exception as e:
        pass  # expected error, we still want to capture trace
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test test_if_else
    tracer = ExecutionTracer(output_file="results/trace_test_if_else_1.jsonl")
    tracer.start_tracing()
    try:
        test_if_else(7)  # x > 0 → "positive"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_if_else_2.jsonl")
    tracer.start_tracing()
    try:
        test_if_else(0)  # x <= 0 → "non-positive"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_if_else_3.jsonl")
    tracer.start_tracing()
    try:
        test_if_else(-5)  # x <= 0 → "non-positive"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test test_nested_if
    tracer = ExecutionTracer(output_file="results/trace_test_nested_if_1.jsonl")
    tracer.start_tracing()
    try:
        test_nested_if(5, 3)  # x>0, y>0 → "both positive"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_nested_if_2.jsonl")
    tracer.start_tracing()
    try:
        test_nested_if(5, -2)  # x>0, y<=0 → "x positive, y not"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_nested_if_3.jsonl")
    tracer.start_tracing()
    try:
        test_nested_if(-1, 4)  # x<=0 → "x not positive"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_nested_if_4.jsonl")
    tracer.start_tracing()
    try:
        test_nested_if(0, 0)  # x<=0 → "x not positive"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test helper
    tracer = ExecutionTracer(output_file="results/trace_helper_1.jsonl")
    tracer.start_tracing()
    try:
        helper("special")  # value == "special" → True
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_helper_2.jsonl")
    tracer.start_tracing()
    try:
        helper("normal")  # value != "special" → False
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_helper_3.jsonl")
    tracer.start_tracing()
    try:
        helper("")  # value != "special" → False
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test main_controller
    tracer = ExecutionTracer(output_file="results/trace_main_controller_1.jsonl")
    tracer.start_tracing()
    try:
        main_controller(15)  # x > 10 → helper("special") → True
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_main_controller_2.jsonl")
    tracer.start_tracing()
    try:
        main_controller(5)  # x <= 10 → helper("normal") → False
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_main_controller_3.jsonl")
    tracer.start_tracing()
    try:
        main_controller(10)  # x <= 10 → helper("normal") → False
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test leaf
    tracer = ExecutionTracer(output_file="results/trace_leaf_1.jsonl")
    tracer.start_tracing()
    try:
        leaf(3)  # a * 2 → 6
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_leaf_2.jsonl")
    tracer.start_tracing()
    try:
        leaf(0)  # a * 2 → 0
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_leaf_3.jsonl")
    tracer.start_tracing()
    try:
        leaf(-2)  # a * 2 → -4
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test middle
    tracer = ExecutionTracer(output_file="results/trace_middle_1.jsonl")
    tracer.start_tracing()
    try:
        middle(2)  # leaf(3)=6 → 5
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_middle_2.jsonl")
    tracer.start_tracing()
    try:
        middle(0)  # leaf(1)=2 → 1
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_middle_3.jsonl")
    tracer.start_tracing()
    try:
        middle(-1)  # leaf(0)=0 → -1
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test root
    tracer = ExecutionTracer(output_file="results/trace_root_1.jsonl")
    tracer.start_tracing()
    try:
        root(1)  # middle(3) → 7 → 17
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_root_2.jsonl")
    tracer.start_tracing()
    try:
        root(0)  # middle(0) → 1 → 11
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_root_3.jsonl")
    tracer.start_tracing()
    try:
        root(-1)  # middle(-3) → -5 → 5
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test processor
    tracer = ExecutionTracer(output_file="results/trace_processor_1.jsonl")
    tracer.start_tracing()
    try:
        processor(4)  # even → "even"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_processor_2.jsonl")
    tracer.start_tracing()
    try:
        processor(7)  # odd → "odd"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_processor_3.jsonl")
    tracer.start_tracing()
    try:
        processor(0)  # even → "even"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test run_loop
    tracer = ExecutionTracer(output_file="results/trace_run_loop_1.jsonl")
    tracer.start_tracing()
    try:
        run_loop([1, 2, 3])  # ["odd", "even", "odd"]
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_run_loop_2.jsonl")
    tracer.start_tracing()
    try:
        run_loop([])  # []
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_run_loop_3.jsonl")
    tracer.start_tracing()
    try:
        run_loop([0, -1, 4])  # ["even", "odd", "even"]
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test test_try_except_finally
    tracer = ExecutionTracer(output_file="results/trace_test_try_except_finally_1.jsonl")
    tracer.start_tracing()
    try:
        test_try_except_finally(5)  # normal → 20.0
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_try_except_finally_2.jsonl")
    tracer.start_tracing()
    try:
        test_try_except_finally(0)  # ZeroDivisionError → "Division by zero"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_try_except_finally_3.jsonl")
    tracer.start_tracing()
    try:
        test_try_except_finally(-3)  # normal → -33.333...
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_try_except_finally_4.jsonl")
    tracer.start_tracing()
    try:
        test_try_except_finally(100)  # normal → 1.0
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_try_except_finally_5.jsonl")
    tracer.start_tracing()
    try:
        test_try_except_finally('a')  # TypeError → "Unknown error occurred"
    except:
        pass
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test test_while_loop
    tracer = ExecutionTracer(output_file="results/trace_test_while_loop_1.jsonl")
    tracer.start_tracing()
    try:
        test_while_loop(3)  # [3, 2, 1]
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_while_loop_2.jsonl")
    tracer.start_tracing()
    try:
        test_while_loop(0)  # []
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_while_loop_3.jsonl")
    tracer.start_tracing()
    try:
        test_while_loop(1)  # [1]
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_test_while_loop_4.jsonl")
    tracer.start_tracing()
    try:
        test_while_loop(-2)  # []
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test risky_function (uncaught — will raise, but trace captured)
    tracer = ExecutionTracer(output_file="results/trace_risky_function_1.jsonl")
    tracer.start_tracing()
    try:
        risky_function(4)  # 16
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_risky_function_2.jsonl")
    tracer.start_tracing()
    try:
        risky_function(0)  # 0
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_risky_function_3.jsonl")
    tracer.start_tracing()
    try:
        risky_function(-2)  # raises RuntimeError — trace still captured
    except RuntimeError:
        pass
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test wrapper
    tracer = ExecutionTracer(output_file="results/trace_wrapper_1.jsonl")
    tracer.start_tracing()
    try:
        wrapper(3)  # 9
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_wrapper_2.jsonl")
    tracer.start_tracing()
    try:
        wrapper(-2)  # "Handled: ..."
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_wrapper_3.jsonl")
    tracer.start_tracing()
    try:
        wrapper(0)  # 0
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    # Test top_level
    tracer = ExecutionTracer(output_file="results/trace_top_level.jsonl")
    tracer.start_tracing()
    try:
        top_level()  # [4, "Handled: ...", 9]
    finally:
        tracer.stop_tracing()
        tracer.save_trace()
        
    # Test SimpleClass.classify via test_class_method
    tracer = ExecutionTracer(output_file="results/trace_class_method_1.jsonl")
    tracer.start_tracing()
    try:
        test_class_method()  # should return "positive"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()

    tracer = ExecutionTracer(output_file="results/trace_class_method_2.jsonl")
    tracer.start_tracing()
    try:
        obj = SimpleClass()
        obj.classify(-3)  # directly call method → "non-positive"
    finally:
        tracer.stop_tracing()
        tracer.save_trace()
        
    validate_traces_against_ground_truth(
        ground_truth_dir="./ground_truths",
        actual_traces_dir="./results"
    )