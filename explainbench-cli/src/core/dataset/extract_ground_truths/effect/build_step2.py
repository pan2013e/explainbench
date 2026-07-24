import json
import os
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

import backoff
from tqdm.auto import tqdm
from pydantic import ValidationError

from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect.infer_expression import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    ExpressionList,
    InferencePersistenceError,
    main as infer_main,
    build_prompt,
)
from dataset.extract_ground_truths.effect.source_util import (
    get_function_code,
    remove_docstrings,
)
from dataset.extract_ground_truths.effect.paid_inference import (
    PaidInferenceJournal,
)

DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE_DIR = os.path.join(DIR, "../../../logs/run_evaluation")
DEFAULT_PREDICTIONS_DIR = os.path.join(
    DIR, "../../explanations/agent_patches"
)
DEFAULT_AGENTS = [
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
PERSISTENCE_FAILURE_EXIT_CODE = 86

def read_json(path):
    with open(os.path.join(path), "r") as f:
        return json.load(f)

@lru_cache
def read_agent_patch_data(agent, predictions_path=None):
    path = predictions_path or os.path.join(
        DEFAULT_PREDICTIONS_DIR, f"{agent}.json"
    )
    with open(path, "r") as f:
        return json.load(f)

def build_fn_code(pre_code, post_code):
    if pre_code == post_code:
        return pre_code
    else:
        return f"# Before Patch:\n{pre_code}\n\n# After Patch:\n{post_code}"

def build_statement(pre_stmt, post_stmt, pre_type, post_type):
    def exc_tag(event_type):
        if event_type == "Exception":
            return " (crashed here)"
        else:
            return " (normally executed)"
    if pre_stmt == post_stmt:
        return pre_stmt
    else:
        return f"# Before Patch:\n{pre_stmt}{exc_tag(pre_type)}\n\n# After Patch:\n{post_stmt}{exc_tag(post_type)}"

def get_agent_patch(agent, instance_id, predictions_path=None):
    data = read_agent_patch_data(agent, predictions_path)
    patch = data[instance_id]['model_patch'] or None
    return patch

def get_simple_function_name(metadata):
    name = metadata['function_name']
    if ":" in name:
        name = name.split(":")[-1]
    if "." in name:
        name = name.split(".")[-1]
    return name

def infer_expressions(
    prompt,
    model_id=DEFAULT_MODEL,
    reasoning_effort=DEFAULT_REASONING_EFFORT,
    env_file=None,
    max_retries=5,
    raw_response_callback=None,
):
    @backoff.on_exception(
        backoff.expo,
        ValidationError,
        max_tries=max_retries,
    )
    def infer_once():
        return infer_main(
            prompt,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            env_file=env_file,
            max_retries=max_retries,
            raw_response_callback=raw_response_callback,
        )

    return infer_once()

def process_agent(
    agent_data,
    agent,
    instance_ids,
    n_changed,
    n_unchanged,
    do_inference,
    predictions_path=None,
    max_workers=20,
    model_id=DEFAULT_MODEL,
    reasoning_effort=DEFAULT_REASONING_EFFORT,
    env_file=None,
    max_retries=5,
    audit_dir=None,
    resume_audit_dirs=(),
):
    results = {}
        
    def process_instance(instance_id):
        try:
            metadata = agent_data[agent][instance_id]
            if metadata is None:
                print(
                    "metadata not found due to step1 error for agent={} | instance_id={}".format(
                        agent,
                        instance_id,
                    )
                )
                return None
            if metadata == {}:
                return {} # fallback to gold
            pre_code, post_code = get_function_code(
                instance_id,
                metadata['file_path'],
                get_simple_function_name(metadata),
                patch=get_agent_patch(agent, instance_id, predictions_path),
                line_hint=(metadata['buggy_lineno'], metadata['patched_lineno']),
            )

            prompt = build_prompt(
                build_fn_code(pre_code, post_code),
                build_statement(
                    metadata["buggy_statement"],
                    metadata["patched_statement"],
                    metadata["buggy_event_type"],
                    metadata["patched_event_type"],
                ),
                metadata["diff"],
                metadata["buggy_variables"],
                metadata["patched_variables"],
                n_changed,
                n_unchanged,
            )
            metadata.pop("diff", None)
            metadata.pop("buggy_variables", None)
            metadata.pop("patched_variables", None)
            instance_result = {"prompt_length_chars": len(prompt)}
            journal = None
            if audit_dir is not None:
                journal = PaidInferenceJournal(
                    audit_dir,
                    prompt=prompt,
                    model_id=model_id,
                    reasoning_effort=reasoning_effort,
                    response_schema=(
                        f"{ExpressionList.__module__}."
                        f"{ExpressionList.__qualname__}"
                    ),
                    resume_directories=tuple(
                        Path(path) for path in resume_audit_dirs
                    ),
                )
            
            if do_inference:
                expr_list = (
                    journal.reuse_response(ExpressionList)
                    if journal is not None
                    else None
                )
                if expr_list is None:
                    expr_list = infer_expressions(
                        prompt,
                        model_id,
                        reasoning_effort,
                        env_file,
                        max_retries,
                        (
                            journal.record_response
                            if journal is not None
                            else None
                        ),
                    )
                    if journal is not None:
                        journal.select_latest_response()
                if expr_list is not None:
                    expr_strings = [x.expr for x in expr_list.expressions]
                    instance_result["changed_candidates"] = expr_strings[:n_changed]
                    instance_result["unchanged_candidates"] = expr_strings[n_changed:] 
                    if journal is not None:
                        instance_result["_source_response"] = (
                            journal.selected_response()
                        )
                instance_result.update(metadata)
                instance_result["function_code_before_patch"] = remove_docstrings(pre_code)
            return instance_result
        except InferencePersistenceError:
            raise
        except Exception as e:
            import traceback, sys
            print(
                "process_agent crashed for agent={} | {}: {} {}".format(
                    agent,
                    instance_id,
                    type(e).__name__,
                    e,
                )
            )
            if not isinstance(e, ValueError):
                traceback.print_exc(file=sys.stdout)
            return None
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_instance, instance_id): instance_id
            for instance_id in instance_ids
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Processing agent {agent}"):
            instance_id = futures[future]
            result = future.result()
            if result is not None:
                results[instance_id] = result
    return results

def build_parser():
    parser = argparse.ArgumentParser(
        description="Generate candidate expressions from step-1 divergences."
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
        "--step1-path",
        default=os.path.join(DEFAULT_BASE_DIR, "output_per_step", "step1.json"),
    )
    parser.add_argument(
        "--output-path",
        default=os.path.join(DEFAULT_BASE_DIR, "output_per_step", "step2.json"),
    )
    parser.add_argument(
        "--gold-output-path",
        default=os.path.join(
            DEFAULT_BASE_DIR, "output_per_step", "step2.gold.json"
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
    parser.add_argument("--changed-candidates", type=int, default=10)
    parser.add_argument("--unchanged-candidates", type=int, default=10)
    parser.add_argument(
        "--inference",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--instance-workers", type=int, default=20)
    parser.add_argument("--agent-workers", type=int, default=10)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high"),
        default=DEFAULT_REASONING_EFFORT,
    )
    parser.add_argument("--env-file")
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument(
        "--audit-dir",
        help=(
            "Store the prompt and raw responses for one selected agent and "
            "instance."
        ),
    )
    parser.add_argument(
        "--resume-audit-dir",
        action="append",
        default=[],
        help="Prior compatible audit directory to inspect before inference.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    selected_agents = args.agent or args.agents or DEFAULT_AGENTS
    if args.predictions_path and (
        len(selected_agents) != 1 or selected_agents[0] == "gold"
    ):
        parser.error(
            "--predictions-path requires exactly one non-gold --agent"
        )
    step1 = read_json(args.step1_path)
    results = {}
    instance_ids = get_instance_ids(args.instance_ids)
    if args.audit_dir and (
        len(selected_agents) != 1 or len(instance_ids) != 1
    ):
        parser.error(
            "--audit-dir requires exactly one selected agent and instance"
        )

    def predictions_path(agent):
        if agent == "gold":
            return None
        return args.predictions_path or os.path.join(
            args.predictions_dir, f"{agent}.json"
        )

    with ThreadPoolExecutor(max_workers=args.agent_workers) as executor:
        futures = {
            executor.submit(
                process_agent,
                step1,
                agent,
                instance_ids,
                args.changed_candidates,
                args.unchanged_candidates,
                args.inference,
                predictions_path(agent),
                args.instance_workers,
                args.model,
                args.reasoning_effort,
                args.env_file,
                args.max_retries,
                args.audit_dir,
                tuple(args.resume_audit_dir),
            ): agent
            for agent in selected_agents
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
    
    if "gold" in results:
        os.makedirs(os.path.dirname(os.path.abspath(args.gold_output_path)), exist_ok=True)
        with open(args.gold_output_path, "w") as f:
            json.dump({"gold": results["gold"]}, f, indent=2)
        print(f"Saved step2 gold results to {args.gold_output_path}")
        del results["gold"]

    os.makedirs(os.path.dirname(os.path.abspath(args.output_path)), exist_ok=True)
    with open(args.output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved step2 results to {args.output_path}")


if __name__ == "__main__":
    try:
        main()
    except InferencePersistenceError as error:
        print(f"Paid response persistence failed: {error}")
        raise SystemExit(PERSISTENCE_FAILURE_EXIT_CODE) from error
