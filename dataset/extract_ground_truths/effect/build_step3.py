import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from itertools import zip_longest
from typing import Any, Dict, Optional, Tuple

from dataset.extract_ground_truths.effect.trace_util import rv_equals
from execution.inspect import main as inspect_main
from execution.util import get_fail_to_pass_tests, get_instance_ids
from tracer.inspector import encode_expr_list
from dataset.extract_ground_truths.effect.source_util import (
    get_function_code,
)
from dataset.extract_ground_truths.effect.build_step2 import (
    DEFAULT_AGENTS,
    DEFAULT_BASE_DIR,
    DEFAULT_PREDICTIONS_DIR,
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
            predictions_path=None,
            run_id=None,
            inspection_cli_args=(),
        ):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        command = [
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
        ]
        if predictions_path is not None:
            command.extend(["--predictions-path", str(predictions_path)])
        if run_id is not None:
            command.extend(["--run-id", run_id])
        command.extend(inspection_cli_args)
        inspect_main(command)

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

def load_inspect_results(
    agent,
    instance_id,
    test_id=0,
    expr_id=0,
    logs_root=None,
    run_id=None,
):
    base_dir = logs_root or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "../../../logs/run_evaluation",
    )
    run_id = run_id or f"inspect.{agent}.{os.getuid()}.{expr_id}"
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

def validate_expressions(
    agent,
    instance_id,
    test_id=0,
    expr_id=0,
    logs_root=None,
    run_id=None,
):
    patched_inspect, buggy_inspect = load_inspect_results(
        agent,
        instance_id,
        test_id,
        expr_id,
        logs_root,
        run_id,
    )
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
    predictions_path: str | None = None
    inspection_run_id: str | None = None
    logs_root: str | None = None
    inspection_cli_args: tuple[str, ...] = ()

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
                predictions_path=job.predictions_path,
                run_id=job.inspection_run_id,
                inspection_cli_args=job.inspection_cli_args,
            )

        if job.do_validate and all_candidates:
            expr_change_map = validate_expressions(
                job.agent,
                job.instance_id,
                test_id=job.test_id,
                expr_id=job.expr_id,
                logs_root=job.logs_root,
                run_id=job.inspection_run_id,
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

def process_agent(
    data,
    agent,
    instance_ids,
    do_execute=True,
    do_validate=True,
    predictions_path=None,
    inspection_run_id=None,
    logs_root=None,
    max_workers=20,
    expression_set_id=0,
    inspection_cli_args=(),
):
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
                patch=get_agent_patch(agent, instance_id, predictions_path),
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
            expr_id=expression_set_id,
            test_id=metadata["test_id"],
            predictions_path=predictions_path,
            inspection_run_id=inspection_run_id,
            logs_root=logs_root,
            inspection_cli_args=tuple(inspection_cli_args),
        ))

    if not jobs:
        results.update(fallback_reachability)
        return results

    Executor = ProcessPoolExecutor if do_execute else ThreadPoolExecutor
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

def build_parser():
    parser = argparse.ArgumentParser(
        description="Execute candidate expressions and/or validate them for effect ground truth step 3.",
    )
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument(
        "--execute",
        action="store_true",
        help="Run execute_candidate_expressions (expression inspection).",
    )
    operation.add_argument(
        "--validate",
        action="store_true",
        help="Validate existing expression-inspection logs and write step 3.",
    )
    agents = parser.add_mutually_exclusive_group()
    agents.add_argument(
        "--agent",
        action="append",
        help="Agent to process; repeat to process multiple agents.",
    )
    agents.add_argument("--agents", nargs="+", help="Agents to process.")
    parser.add_argument(
        "--instance-ids",
        "--instance_ids",
        nargs="+",
        default=["all"],
    )
    parser.add_argument(
        "--step2-path",
        default=os.path.join(DEFAULT_BASE_DIR, "output_per_step", "step2.json"),
    )
    parser.add_argument(
        "--gold-step2-path",
        default=os.path.join(
            DEFAULT_BASE_DIR, "output_per_step", "step2.gold.json"
        ),
    )
    parser.add_argument(
        "--output-path",
        default=os.path.join(DEFAULT_BASE_DIR, "output_per_step", "step3.json"),
    )
    parser.add_argument(
        "--gold-output-path",
        default=os.path.join(
            DEFAULT_BASE_DIR, "output_per_step", "step3.gold.json"
        ),
    )
    parser.add_argument(
        "--predictions-path",
        help="Predictions JSON for exactly one selected non-gold agent.",
    )
    parser.add_argument(
        "--predictions-dir",
        default=DEFAULT_PREDICTIONS_DIR,
        help="Directory containing historical {agent}.json prediction files.",
    )
    parser.add_argument(
        "--inspection-run-id-template",
        help=(
            "Inspection run ID, optionally containing {agent} and {expr_id}. "
            "Defaults to the historical agent/UID form."
        ),
    )
    parser.add_argument(
        "--logs-root",
        default=DEFAULT_BASE_DIR,
        help="Root containing SWE-bench run-evaluation log directories.",
    )
    parser.add_argument("--expression-set-id", type=int, default=0)
    parser.add_argument("--instance-workers", type=int, default=20)
    parser.add_argument("--agent-workers", type=int, default=10)
    parser.add_argument("--inspection-timeout", type=int, default=3600)
    parser.add_argument(
        "--inspection-dataset-name",
        default="SWE-bench/SWE-bench_Verified",
    )
    parser.add_argument("--inspection-split", default="test")
    parser.add_argument("--inspection-namespace", default="swebench")
    parser.add_argument("--inspection-max-workers", type=int, default=0)
    parser.add_argument(
        "--inspection-force-rebuild",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--inspection-cache-level", default="env")
    parser.add_argument(
        "--inspection-clean",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--inspection-open-file-limit", type=int, default=4096)
    parser.add_argument(
        "--inspection-rewrite-reports",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--inspection-modal",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--inspection-instance-image-tag", default="latest")
    parser.add_argument("--inspection-env-image-tag", default="latest")
    parser.add_argument("--inspection-report-dir", default=".")
    parser.add_argument(
        "--inspection-work-dir",
        default=".",
        help="Working directory that contains SWE-bench inspection logs.",
    )
    parser.add_argument(
        "--process-gold",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Execute gold metadata when a reusable gold step-3 file is absent.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    do_execute = args.execute
    do_validate = args.validate
    selected_agents = args.agent or args.agents or DEFAULT_AGENTS
    if args.predictions_path and (
        len(selected_agents) != 1 or selected_agents[0] == "gold"
    ):
        parser.error(
            "--predictions-path requires exactly one non-gold --agent"
        )

    print(
        f"[INFO] Step3 main starting "
        f"(execute={do_execute}, validate={do_validate})",
    )

    step2 = read_json(args.step2_path)
    gold = read_json(args.gold_step2_path)
    step2["gold"] = gold["gold"]
    results = {}
    agents_to_process = [agent for agent in selected_agents if agent != "gold"]
    instance_ids = get_instance_ids(args.instance_ids)

    def predictions_path(agent):
        if agent == "gold":
            return None
        return args.predictions_path or os.path.join(
            args.predictions_dir, f"{agent}.json"
        )

    def inspection_run_id(agent):
        if args.inspection_run_id_template is None:
            return None
        return args.inspection_run_id_template.format(
            agent=agent,
            expr_id=args.expression_set_id,
        )

    inspection_cli_args = (
        "--timeout", str(args.inspection_timeout),
        "--dataset-name", args.inspection_dataset_name,
        "--split", args.inspection_split,
        "--namespace", args.inspection_namespace,
        "--max-workers", str(args.inspection_max_workers),
        "--cache-level", args.inspection_cache_level,
        "--open-file-limit", str(args.inspection_open_file_limit),
        "--instance-image-tag", args.inspection_instance_image_tag,
        "--env-image-tag", args.inspection_env_image_tag,
        "--report-dir", args.inspection_report_dir,
        "--work-dir", args.inspection_work_dir,
        "--force-rebuild" if args.inspection_force_rebuild else "--no-force-rebuild",
        "--clean" if args.inspection_clean else "--no-clean",
        "--rewrite-reports" if args.inspection_rewrite_reports else "--no-rewrite-reports",
        "--modal" if args.inspection_modal else "--no-modal",
    )

    # Run gold patch first
    if os.path.exists(args.gold_output_path):
        if do_validate:
            results["gold"] = read_json(args.gold_output_path)["gold"]
            print(f"[INFO] Loaded existing step3.gold.json with {len(results['gold'])} entries")
    elif args.process_gold:
        print("[INFO] Processing gold agent for step3")
        results["gold"] = process_agent(
            step2,
            "gold",
            instance_ids,
            do_execute,
            do_validate,
            inspection_run_id=inspection_run_id("gold"),
            logs_root=args.logs_root,
            max_workers=args.instance_workers,
            expression_set_id=args.expression_set_id,
            inspection_cli_args=inspection_cli_args,
        )
        if do_validate:
            os.makedirs(
                os.path.dirname(os.path.abspath(args.gold_output_path)),
                exist_ok=True,
            )
            with open(args.gold_output_path, "w") as f:
                json.dump(results, f, indent=2)
            print(f"Saved step3 results to {args.gold_output_path}")
    elif do_validate:
        parser.error(
            "validation requires --gold-output-path to exist or --process-gold"
        )
    if do_validate:
        step2["gold"] = results["gold"]

    with ThreadPoolExecutor(max_workers=args.agent_workers) as executor:
        futures = {
            executor.submit(
                process_agent,
                step2,
                agent,
                instance_ids,
                do_execute,
                do_validate,
                predictions_path(agent),
                inspection_run_id(agent),
                args.logs_root,
                args.instance_workers,
                args.expression_set_id,
                inspection_cli_args,
            ): agent
            for agent in agents_to_process
        }
        for future in as_completed(futures):
            agent = futures[future]
            results[agent] = future.result()
            print(f"[INFO] Completed processing for agent={agent}")
    
    if do_validate:
        os.makedirs(
            os.path.dirname(os.path.abspath(args.output_path)),
            exist_ok=True,
        )
        with open(args.output_path, "w") as f:
            if "gold" in results:
                del results["gold"]
            json.dump(results, f, indent=2)
        print(f"Saved step3 results to {args.output_path}")


if __name__ == "__main__":
    main()
