import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from typing import Any, Dict, Optional, Tuple

from explainbench.question_builders.local.stages.validate_candidate_expressions import (
    compute_expression_changes,
    expression_value_changed,
)
from execution.inspect import main as inspect_main
from execution.util import get_fail_to_pass_tests, get_instance_ids
from tracer.inspector import encode_expr_list
from dataset.extract_ground_truths.effect.source_util import (
    get_function_code,
)
from dataset.extract_ground_truths.effect.build_step2 import (
    get_agent_patch,
    get_simple_function_name,
)

def read_json(input_path):
    with open(input_path, "r") as f:
        return json.load(f)

def extract_qualname(func_name):
    idx = func_name.find(':')
    if idx == -1:
        return func_name
    return func_name[idx+1:]

def execute_candidate_expressions(
            expression_candidates: list,
            instance_id: str,
            agent: str,
            file_path: str,
            buggy_lineno: int,
            patched_lineno: int,
            buggy_line_count: int,
            patched_line_count: int,
            before_or_after: str,
            bp_func_name: str,
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
            "--bp-func", bp_func_name,
        ])

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
    return expression_value_changed(
        buggy_val,
        buggy_exc,
        patched_val,
        patched_exc,
    )

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
    return compute_expression_changes(patched, buggy)

def load_inspect_results(agent, instance_id, test_id=0, expr_id=0):
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../logs/run_evaluation")
    run_id = f"inspect.{agent}.{os.getuid()}.{expr_id}"
    log_dir = os.path.join(base_dir, run_id, agent, instance_id)
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    buggy_path = os.path.join(log_dir, f"buggy_traces/{test_name}.jsonl")
    patched_path = os.path.join(log_dir, f"patched_traces/{test_name}.jsonl")
    if not os.path.exists(buggy_path) or not os.path.exists(patched_path):
        print(f"Inspection results not found for {instance_id}, test {test_name}")
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

        changed_candidates = metadata.get("changed_candidates", [])
        unchanged_candidates = metadata.get("unchanged_candidates", [])
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
                metadata["buggy_line_count"],
                metadata["patched_line_count"],
                metadata["before_or_after"],
                extract_qualname(metadata["function_name"]),
                expr_id=job.expr_id,
            )

        if job.do_validate and all_candidates:
            expr_change_map = validate_expressions(
                job.agent,
                job.instance_id,
                test_id=job.test_id,
                expr_id=job.expr_id,
            )

            if not all(k in all_candidates for k in expr_change_map.keys()):
                print(f"[ERROR] {job.agent} {job.instance_id}")
                print(expr_change_map)
                print("----")
                print(all_candidates)
                
            valid_changed = [e for e, changed in expr_change_map.items() if changed is True]
            valid_unchanged = [e for e, changed in expr_change_map.items() if changed is False]


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
            if "gold" not in data or instance_id not in data["gold"]:
                print(f"During processing of fallback, gold patch metadata not found for instance {instance_id}")
                continue
            # Use gold metadata that was already run
            metadata = data["gold"][instance_id]
            pre_code, _ = get_function_code(
                instance_id,
                metadata['file_path'],
                get_simple_function_name(metadata),
                patch=get_agent_patch(agent, instance_id),
                line_hint=(metadata['buggy_lineno'], metadata['patched_lineno']),
            )
            metadata["function_code_before_patch"] = pre_code
            is_fallback_to_gold = True
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
    )

    return results

if __name__ == "__main__":
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
    )

    # ------------ SCRIPT PARAMETERS ------------ #
    BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../logs/run_evaluation")
    AGENTS = [
        "20250603_Refact_Agent_claude-4-sonnet",
        "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
        "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
        "20250928_trae_doubao_seed_code",
        "20250807_mini-v1.7.0_gpt-5-mini",
        "20251127_openhands_claude-opus-4-5",
        "openhands_gpt-5-mini",
        "openhands_minimax-m2.5",
        "gold",
    ]
    STEP2_PATH = os.path.join(BASE_DIR, "output_per_step", "step2.json")
    OUTPUT_PATH = os.path.join(BASE_DIR, "output_per_step", "step3.json")
    STEP2_GOLD_PATH = os.path.join(BASE_DIR, "output_per_step", "step2.gold.json")
    STEP3_GOLD_PATH = os.path.join(BASE_DIR, "output_per_step", "step3.gold.json")
    FRESH_RUN = False
    # ------------------------------------------- #
    
    step2 = read_json(STEP2_PATH)
    gold = read_json(STEP2_GOLD_PATH)
    step2["gold"] = gold["gold"]
    
    results = {}
    if os.path.exists(OUTPUT_PATH) and not FRESH_RUN:
        with open(OUTPUT_PATH, "r") as f:
            exist_agents = list(json.load(f).keys())
        OUTPUT_PATH = OUTPUT_PATH.replace(".json" ,".incremental.json")
    else:
        exist_agents = []
    
    agents_to_process = AGENTS.copy()
    agents_to_process = [agent for agent in agents_to_process if agent not in exist_agents]
    if "gold" in agents_to_process:
        agents_to_process.remove("gold")

    instance_ids = get_instance_ids(["all"])
    
    # Run gold patch first
    if os.path.exists(STEP3_GOLD_PATH):
        if do_validate:
            results["gold"] = read_json(STEP3_GOLD_PATH)["gold"]
            print(f"[INFO] Loaded existing step3.gold.json with {len(results['gold'])} entries")
    else:
        print("[INFO] Processing gold agent for step3")
        results["gold"] = process_agent(step2, "gold", instance_ids, do_execute, do_validate)
        if do_validate:
            with open(os.path.join(STEP3_GOLD_PATH), "w") as f:
                json.dump(results, f, indent=2)
            print(f"Saved step3 results to {STEP3_GOLD_PATH}")
    if do_validate:
        step2["gold"] = results["gold"]

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, step2, agent, instance_ids, do_execute, do_validate): agent for agent in agents_to_process
        }
        for future in as_completed(futures):
            agent = futures[future]
            results[agent] = future.result()
            print(f"[INFO] Completed processing for agent={agent}")
    
    if do_validate:
        with open(os.path.join(OUTPUT_PATH), "w") as f:
            if "gold" in results:
                del results["gold"]
            json.dump(results, f, indent=2)
        print(f"Saved step3 results to {OUTPUT_PATH}")
