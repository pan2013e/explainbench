# Build ground truth for effect
# Step 2. Provide step 1 info to an LLM to infer an expression,
# then inspect the expr value in buggy and patched versions
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from itertools import zip_longest
from typing import Any, Dict, Optional, Tuple

from deepdiff import DeepDiff
from tqdm.auto import tqdm

from dataset.extract_ground_truths.effect.build_step1 import AGENTS, DIR
from dataset.extract_ground_truths.effect.trace_util import rv_equals
from execution.inspect import main as inspect_main
from execution.util import get_fail_to_pass_tests, get_instance_ids
from tracer.inspector import encode_expr_list

def read_json(input_path):
    with open(input_path, "r") as f:
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
        changed = index_changed(bv, be, pv, pe)
        expr_change[expr] = changed

    return expr_change


def load_inspect_results(agent, instance_id, test_id=0, expr_id=0):
    run_id = f"inspect.{agent}.1020.{expr_id}"
    log_dir = os.path.join(
        "/home/yusuf/explainbench/shared_logs/logs/run_evaluation",
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

@dataclass(frozen=True)
class InstanceJob:
    agent: str
    instance_id: str
    metadata: Dict[str, Any]
    do_execute: bool
    do_validate: bool
    expr_id: int = 0
    test_id: int = 0

def run_instance_job(job: InstanceJob) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Returns: (instance_id, result_dict_or_None)
    This is process-safe as long as job contains only picklable data.
    """
    try:
        metadata = job.metadata
        if not metadata:
            return job.instance_id, None

        changed_candidates = metadata["changed_candidates"]
        unchanged_candidates = metadata["unchanged_candidates"]
        all_candidates = changed_candidates + unchanged_candidates

        result: Dict[str, Any] = {}

        if job.do_execute and all_candidates:
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
                expr_id=job.expr_id,
            )

        if job.do_validate and all_candidates:
            expr_change_map = validate_expressions(
                job.agent,
                job.instance_id,
                test_id=job.test_id,
                expr_id=job.expr_id,
            )

            valid_changed = [e for e in changed_candidates if expr_change_map.get(e) is True]
            valid_unchanged = [e for e in unchanged_candidates if expr_change_map.get(e) is False]

            result["valid_changed_expressions"] = valid_changed
            result["valid_unchanged_expressions"] = valid_unchanged

        result.update(metadata)
        return job.instance_id, result

    except Exception as e:
        print(f"[ERROR] run_instance_job crashed for agent={job.agent} | {job.instance_id}: {type(e).__name__} {e}")
        return job.instance_id, None

def process_agent(data, agent, instance_ids, do_execute=True, do_validate=True):
    results = {}
    fallback_reachability = {}
    print(
        f"[INFO] Starting process_agent for agent={agent} "
        f"with {len(instance_ids)} instances "
        f"(execute={do_execute}, validate={do_validate})",
        flush=True,
    )

    jobs = []
    for instance_id in instance_ids:
        if agent not in data:
            continue
        if instance_id not in data[agent]:
            continue
        metadata = data[agent][instance_id]
        if metadata is None:
            continue
        is_fallback_to_gold = False
        if metadata == {}:
            print(f"Falling back to gold for instance {instance_id}")
            if "gold" not in data or instance_id not in data["gold"]:
                print(f"Gold patch metadata not found for instance {instance_id}")
                continue
            # Use gold metadata that was already run
            metadata = data["gold"][instance_id]
            is_fallback_to_gold = True
        if metadata.get("choices"):
            print(f"Falling back to reachability question in step 4 for instance {instance_id}")
            fallback_reachability[instance_id] = metadata
            continue
        metadata = dict(metadata)
        metadata["is_fallback_to_gold"] = is_fallback_to_gold
        jobs.append(InstanceJob(
            agent=agent,
            instance_id=instance_id,
            metadata=metadata,
            do_execute=False if is_fallback_to_gold else do_execute,
            do_validate=False if is_fallback_to_gold else do_validate,
            expr_id=0,
            test_id=metadata["test_id"],
        ))

    if not jobs:
        results.update(fallback_reachability)
        return results

    Executor = ProcessPoolExecutor if do_execute else ThreadPoolExecutor
    max_workers = 20

    with Executor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_instance_job, job): job.instance_id for job in jobs}
        for future in as_completed(futures):
            iid = futures[future]
            try:
                instance_id, res = future.result()
                results[instance_id] = res
            except Exception as e:
                print(f"[ERROR] Future failed for agent={agent} | {iid}: {type(e).__name__} {e}")
                results[iid] = None

    results.update(fallback_reachability)
    
    print(
        f"[INFO] Finished process_agent for agent={agent}; "
        f"processed {len(results)} instances",
        flush=True,
    )

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

    print(
        f"[INFO] Step3 main starting "
        f"(execute={do_execute}, validate={do_validate})",
        flush=True,
    )

    STEP2_PATH = os.path.join("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step", "step2.combined.json")
    GOLD_PATH = os.path.join("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step", "step2.gold.combined.json")
    step2 = read_json(STEP2_PATH)
    gold = read_json(GOLD_PATH)
    step2["gold"] = gold["gold"]
    
    results = {}
    instance_ids = get_instance_ids(["all"])
    
    # Run gold patch first
    STEP3_GOLD_PATH = os.path.join("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step", "step3.gold.json")
    if os.path.exists(STEP3_GOLD_PATH):
        if do_validate:
            results["gold"] = read_json(STEP3_GOLD_PATH)
            print(f"[INFO] Loaded existing step3.gold.json with {len(results['gold'])} entries", flush=True)
    else:
        results["gold"] = process_agent(step2, "gold", instance_ids, do_execute, do_validate)
        if do_validate:
            with open(os.path.join("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step", "step3.gold.json"), "w") as f:
                json.dump(results, f, indent=2)
            print("Saved step3 results to /home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/step3.gold.json")

    with ThreadPoolExecutor(max_workers=10) as executor:        
        futures = {
            executor.submit(process_agent, step2, agent, instance_ids, do_execute, do_validate): agent
            for agent in AGENTS if agent and agent != "gold"
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
            print(f"[INFO] Completed processing for agent={agent}", flush=True)
    
    if do_validate:
        with open(os.path.join("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step", "step3.json"), "w") as f:
            if "gold" in results:
                del results["gold"]
            json.dump(results, f, indent=2)
        print("Saved step3 results to /home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/step3.json")
    
    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")
    
if __name__ == "__main__":
    main()
