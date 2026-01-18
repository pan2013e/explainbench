# Build ground truth for effect
# Step 2. Provide step 1 info to an LLM to infer an expression,
# then inspect the expr value in buggy and patched versions
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

import backoff
from tqdm.auto import tqdm
from pydantic import ValidationError

from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect.infer_expression import (
    main as infer_main,
    build_prompt,
)
from dataset.extract_ground_truths.effect.source_util import (
    get_function_code,
    remove_docstrings,
)

def read_json(path):
    with open(os.path.join(path), "r") as f:
        return json.load(f)

@lru_cache
def read_agent_patch_data(agent):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"../../explanations/agent_patches/{agent}.json"), "r") as f:
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

def get_agent_patch(agent, instance_id):
    data = read_agent_patch_data(agent)
    patch = data[instance_id]['model_patch'] or None
    return patch

def get_simple_function_name(metadata):
    name = metadata['function_name']
    if ":" in name:
        name = name.split(":")[-1]
    if "." in name:
        name = name.split(".")[-1]
    return name

@backoff.on_exception(backoff.expo, ValidationError, max_tries=5)
def infer_expressions(prompt):
    expr = infer_main(prompt)
    return expr

def process_agent(
    agent_data,
    agent,
    instance_ids,
    n_changed,
    n_unchanged,
    do_inference,
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
                patch=get_agent_patch(agent, instance_id),
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
            
            if do_inference:
                expr_list = infer_expressions(prompt)
                if expr_list is not None:
                    expr_strings = [x.expr for x in expr_list.expressions]
                    instance_result["changed_candidates"] = expr_strings[:n_changed]
                    instance_result["unchanged_candidates"] = expr_strings[n_changed:] 
                instance_result.update(metadata)
                instance_result["function_code_before_patch"] = remove_docstrings(pre_code)
            return instance_result
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
    
    with ThreadPoolExecutor(max_workers=20) as executor:
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

if __name__ == "__main__":
    # ------------ SCRIPT PARAMETERS ------------ #
    BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../logs/run_evaluation")
    RQ1_AGENTS = [
        "20250603_Refact_Agent_claude-4-sonnet",
        "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
        "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
        "20250928_trae_doubao_seed_code",
        "20250807_mini-v1.7.0_gpt-5-mini",
        "gold",
    ]
    # Assume gold has been processed in RQ1
    RQ3_AGENTS = [
        "rq3_v1",
    ]
    RUN_RQ3 = False
    if RUN_RQ3:
        print("Running RQ3")
        AGENTS = RQ3_AGENTS
        STEP1_PATH = os.path.join(BASE_DIR, "output_per_step_rq3", "step1.json")
        OUTPUT_PATH = os.path.join(BASE_DIR, "output_per_step_rq3", "step2.json")
    else:
        print("Running RQ1")
        AGENTS = RQ1_AGENTS
        STEP1_PATH = os.path.join(BASE_DIR, "output_per_step", "step1.json")
        OUTPUT_PATH = os.path.join(BASE_DIR, "output_per_step", "step2.json")
    STEP2_GOLD_PATH = os.path.join(BASE_DIR, "output_per_step", "step2.gold.json")
    N_CHANGED = 10
    N_UNCHANGED = 10
    DO_INFERENCE = True
    FRESH_RUN = False
    # ------------------------------------------- #

    step1 = read_json(STEP1_PATH)
    results = {}
    if os.path.exists(OUTPUT_PATH) and not FRESH_RUN:
        with open(OUTPUT_PATH, "r") as f:
            exist_agents = list(json.load(f).keys())
        OUTPUT_PATH = OUTPUT_PATH.replace(".json" ,".incremental.json")
    else:
        exist_agents = []

    agents_to_process = AGENTS.copy()
    agents_to_process = [agent for agent in agents_to_process if agent not in exist_agents]
    
    if os.path.exists(STEP2_GOLD_PATH) and "gold" in agents_to_process:
        agents_to_process.remove("gold")

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(
                process_agent,
                step1,
                agent,
                get_instance_ids(["all"]),
                N_CHANGED,
                N_UNCHANGED,
                DO_INFERENCE
            ): agent
            for agent in agents_to_process
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
    
    if "gold" in results:
        with open(STEP2_GOLD_PATH, "w") as f:
            json.dump({"gold": results["gold"]}, f, indent=2)
        print(f"Saved step2 gold results to {STEP2_GOLD_PATH}")
        del results["gold"]
    
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved step2 results to {OUTPUT_PATH}")
