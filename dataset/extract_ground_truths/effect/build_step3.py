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

def index_changed(buggy_val, buggy_exc, patched_val, patched_exc):
    # values are equal, no change.
    if rv_equals(buggy_val, patched_val):
        return False

    # Values differ.
    # That is: one value is None, the other is not, and the side with None has
    # an AttributeError on NoneType during evaluation.
    if (buggy_val is None) != (patched_val is None):
        exc = buggy_exc if buggy_val is None else patched_exc
        if is_none_attr_inspection_failure(exc):
            return True
        return False

    # Otherwise, treat any value difference as a change.
    return True

def index_selected(buggy_val, buggy_exc, patched_val, patched_exc, should_change: bool):
    changed = index_changed(buggy_val, buggy_exc, patched_val, patched_exc)
    return changed if should_change else not changed

def get_valid_expressions(patched, buggy, should_change):
    valid_expressions = []
    for i, (pv, pe, bv, be) in enumerate(
        zip(patched["value"], patched["exception"],
            buggy["value"], buggy["exception"])
    ):
        if index_selected(pv, pe, bv, be, should_change=should_change):
            valid_expressions.append(patched["expr"][i])
            assert patched["expr"][i] == buggy["expr"][i], "Expression does not match"
    return valid_expressions

def validate_expressions(agent, instance_id, should_change, expr_id=0, test_id=0):
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
        # raise RuntimeError("Inspection failed, results not found.")
        return []

    with open(buggy_path, "r") as f:
        buggy_inspect = json.load(f)

    with open(patched_path, "r") as f:
        patched_inspect = json.load(f)
        
    valid_expressions = get_valid_expressions(patched_inspect, buggy_inspect, should_change)
    return valid_expressions
    
def process_agent(data, agent, instance_ids, do_execute=True, do_validate=True):
    results = {}
    for instance_id in instance_ids:
        for idx, key in enumerate(["changed_candidates", "unchanged_candidates"]):
            output_key = "valid_changed_expressions" if key == "changed_candidates" else "valid_unchanged_expressions"
            if instance_id not in results:
                results[instance_id] = {}
            
            metadata = data[agent][instance_id]
            if metadata is None:
                results[instance_id] = None
                continue
            expression_candidates = metadata[key] 
            if do_execute:
                execute_candidate_expressions(
                        expression_candidates,
                        metadata["instance_id"],
                        metadata["agent"],
                        metadata["file_path"],
                        metadata["buggy_lineno"],
                        metadata["patched_lineno"],
                        metadata["test_id"],
                        metadata["buggy_line_count"],
                        metadata["patched_line_count"],
                        metadata["before_or_after"],
                        expr_id=idx                
                    )
            if do_validate:
                valid_expressions = validate_expressions(
                                            agent,
                                            instance_id,
                                            should_change=key == "changed_candidates",
                                            test_id=0,
                                            expr_id=idx)
                results[instance_id][output_key] = valid_expressions,
        results[instance_id].update(metadata)
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
    list_ids = [
        # "astropy__astropy-12907",
        "astropy__astropy-13453",
        "astropy__astropy-13579",
        "astropy__astropy-14096",
        "sympy__sympy-12096",
        "sympy__sympy-12419",
        "sympy__sympy-12489",
        "sympy__sympy-13615",
    ]
    instance_ids = get_instance_ids(list_ids)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, step2, agent, instance_ids, do_execute, do_validate): agent
            for agent in AGENTS if agent
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