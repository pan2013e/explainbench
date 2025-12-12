# Build ground truth for effect
# Step 2. Provide step 1 info to an LLM to infer an expression,
# then inspect the expr value in buggy and patched versions
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from itertools import zip_longest

from deepdiff import DeepDiff
from tqdm.auto import tqdm

from dataset.extract_ground_truths.effect.build_step1 import AGENTS, DIR
from dataset.extract_ground_truths.effect.trace_util import rv_equals
from execution.inspect import main as inspect_main
from execution.util import get_fail_to_pass_tests, get_instance_ids
from tracer.inspector import encode_expr_list


def read_step2_results():
    with open(os.path.join(DIR, "tmp/step2.json"), "r") as f:
        return json.load(f)

def execute_candidate_expressions(
            expression_candidates: list,
            instance_id: str,
            agent: str,
            file_path: str,
            buggy_lineno: int,
            patched_lineno: int,
            test_id: int,
            buggy_line_count: int,
            patched_line_count: int,
            before_or_after: str,
            should_change=True,
            expr_id=0,
        ):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        inspect_main([
            "--instance_id", instance_id,
            "--agent", agent,
            "--bp-file", file_path,
            "--pre-bp-line", str(buggy_lineno),
            "--post-bp-line", str(patched_lineno),
            "--expr", encode_expr_list(expression_candidates),
            "--expr-id", str(expr_id),
            "--pre-count", str(buggy_line_count),
            "--post-count", str(patched_line_count),
            "--inspector-mode", before_or_after,
        ])
            
def rv_equals(v1, v2):
    diff = DeepDiff(v1, v2, significant_digits=5, ignore_private_variables=False)
    return diff == {}

def is_none_attr_inspection_failure(exc):
    if exc is None:
        return False
    stage = exc.get("stage")
    etype = exc.get("type")
    msg = exc.get("message", "")
    return (
        stage == "evaluation"
        and etype == "AttributeError"
        and "NoneType" in msg
    )

def is_name_error(exc):
    if exc is None:
        return False
    stage = exc.get("stage")
    etype = exc.get("type")
    return (
        stage == "evaluation"
        and etype == "NameError"
    )

def index_changed(buggy_val, buggy_exc, patched_val, patched_exc):
    # values are equal, no change.
    if rv_equals(buggy_val, patched_val):
        return False

    # Values differ.
    # That is: one value is None, the other is not, and the side with None has
    # an AttributeError on NoneType during evaluation.
    if (buggy_val is None) != (patched_val is None):
        exc = buggy_exc if buggy_val is None else patched_exc
        if is_none_attr_inspection_failure(exc) or is_name_error(exc):
            return True
        return False

    # Otherwise, treat any value difference as a change.
    return True

def index_selected(buggy_val, buggy_exc, patched_val, patched_exc, should_change: bool):
    changed = index_changed(buggy_val, buggy_exc, patched_val, patched_exc)
    return changed if should_change else not changed

def _ensure_list(x, length):
    if isinstance(x, list):
        return x
    if x is None:
        return [None] * length
    # Broadcast scalars / dicts across all positions
    return [x] * length

def _max_len(*items):
    return max(len(x) for x in items if isinstance(x, list))

def compute_expr_change_map(patched, buggy):
    n = _max_len(
        patched.get("expr"),
        patched.get("value"),
        patched.get("exception"),
        buggy.get("expr"),
        buggy.get("value"),
        buggy.get("exception"),
    )

    p_expr = _ensure_list(patched.get("expr"), n)
    p_vals = _ensure_list(patched.get("value"), n)
    p_excs = _ensure_list(patched.get("exception"), n)

    b_expr = _ensure_list(buggy.get("expr"), n)
    b_vals = _ensure_list(buggy.get("value"), n)
    b_excs = _ensure_list(buggy.get("exception"), n)

    expr_change = {}
    for i, (expr, pv, pe, bv, be) in enumerate(
        zip_longest(p_expr, p_vals, p_excs, b_vals, b_excs, fillvalue=None)
    ):
        changed = index_changed(pv, pe, bv, be)
        expr_change[expr] = changed

    return expr_change


def load_inspect_results(agent, instance_id, test_id=0, expr_id=0):
    run_id = f"inspect.{agent}.{os.getuid()}.{expr_id}"
    log_dir = os.path.join(
        DIR,
        "../../../logs/run_evaluation",
        run_id,
        agent,
        instance_id,
    )
    stdout = StringIO()
    stderr = StringIO()
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    buggy_path = os.path.join(log_dir, f"buggy_traces/{test_name}.jsonl")
    patched_path = os.path.join(log_dir, f"patched_traces/{test_name}.jsonl")
    if not os.path.exists(buggy_path) or not os.path.exists(patched_path):
        print(f"Inspection results not found for {instance_id}, test {test_name}")
        print(f"Inspection stdout:\n{stdout.getvalue()}")
        print(f"Inspection stderr:\n{stderr.getvalue()}")
        return None, None

    with open(buggy_path, "r") as f:
        buggy_inspect = json.load(f)
    with open(patched_path, "r") as f:
        patched_inspect = json.load(f)
    return patched_inspect, buggy_inspect

def validate_expressions(agent, instance_id, test_id=0, expr_id=0):
    patched_inspect, buggy_inspect = load_inspect_results(agent, instance_id, test_id, expr_id)
    if patched_inspect is None:
        return {}
    return compute_expr_change_map(patched_inspect, buggy_inspect)

def process_agent(data, agent, instance_ids, do_execute=True, do_validate=True):
    results = {}
    
    def process_instance(instance_id):
        try:
            if instance_id not in data[agent]:
                return None
            metadata = data[agent][instance_id]
            if metadata is None:
                return None

            changed_candidates = metadata["changed_candidates"]
            unchanged_candidates = metadata["unchanged_candidates"]

            all_candidates = changed_candidates + unchanged_candidates

            result = {}

            if do_execute and all_candidates:
                execute_candidate_expressions(
                    all_candidates,
                    metadata["instance_id"],
                    metadata["agent"],
                    metadata["file_path"],
                    metadata["buggy_lineno"],
                    metadata["patched_lineno"],
                    metadata["test_id"],
                    metadata["buggy_line_count"],
                    metadata["patched_line_count"],
                    metadata["before_or_after"],
                    expr_id=0,
                )
                                
            if do_validate and all_candidates:
                expr_change_map = validate_expressions(
                    agent,
                    instance_id,
                    test_id=0,
                    expr_id=0,
                )

                valid_changed = [
                    e for e in changed_candidates
                    if expr_change_map.get(e) is True
                ]
                valid_unchanged = [
                    e for e in unchanged_candidates
                    if expr_change_map.get(e) is False
                ]

                result["valid_changed_expressions"] = valid_changed
                result["valid_unchanged_expressions"] = valid_unchanged
           
            result.update(metadata)
            return result
        except Exception as e:
            print(f"[ERROR] process_agent crashed for agent={agent} | {instance_id}: {type(e).__name__} {e}")
            return None
    
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(process_instance, instance_id): instance_id for instance_id in instance_ids}
        for future in as_completed(futures):
            instance_id = futures[future]
            results[instance_id] = future.result()
    
    return results

def main():

    start_time = time.time()
    
    parser = argparse.ArgumentParser(
        description="Execute candidate expressions and/or validate them for effect ground truth step 3.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run execute_candidate_expressions (expression inspection).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validate_expressions and write tmp/step3.json.",
    )
    args = parser.parse_args()

    do_execute = args.execute
    do_validate = args.validate
        
    step2 = read_step2_results()
    results = {}
    instance_ids = get_instance_ids(["all"])
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, step2, agent, instance_ids, do_execute, do_validate): agent
            for agent in AGENTS if agent and agent != "gold"
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
    
    if do_validate:
        with open(os.path.join(DIR, "tmp/step3.json"), "w") as f:
            json.dump(results, f, indent=2)
        print("Saved step3 results to tmp/step3.json")
    
    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")
    
if __name__ == "__main__":
    main()