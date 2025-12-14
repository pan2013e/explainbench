# Build ground truth for effect
# Step 2. Provide step 1 info to an LLM to infer an expression,
# then inspect the expr value in buggy and patched versions
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

import backoff
from tqdm.auto import tqdm

from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect.build_step1 import AGENTS, DIR
from dataset.extract_ground_truths.effect.infer_expression import main as infer_main
from dataset.extract_ground_truths.effect.source_util import (
    get_function_code,
    remove_docstrings,
)

logger = logging.getLogger(__name__)

def read_json(path):
    with open(os.path.join(path), "r") as f:
        return json.load(f)

@lru_cache
def read_agent_patch_data(agent):
    with open(os.path.join(DIR, f"../../explanations/agent_patches/{agent}.json"), "r") as f:
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

@backoff.on_exception(backoff.expo, Exception, max_tries=5)
def infer_expressions(pre_code, post_code, metadata, should_change, changed_expressions):
    expr = infer_main(
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
        should_change,
        changed_expressions
    )
    return expr

def process_agent(agent_data, agent, instance_ids):
    results = {}
        
    def process_instance(instance_id):
        try:
            metadata = agent_data[agent][instance_id]
            if metadata is None:
                print(
                    "metadata not found due to errors for agent=%s | instance_id=%s",
                    agent,
                    instance_id,
                )
                return None
            if metadata == {}:
                print(
                    "no behavior delta for agent=%s | instance_id=%s, need to fallback to gold in step 3",
                    agent,
                    instance_id,
                )
                return {}
            pre_code, post_code = get_function_code(
                instance_id,
                metadata['file_path'],
                get_simple_function_name(metadata),
                patch=get_agent_patch(agent, instance_id),
                line_hint=(metadata['buggy_lineno'], metadata['patched_lineno']),
            )

            instance_result = {}
            changed_expressions = None
            for should_change in (True, False):
                expr_list = infer_expressions(
                    pre_code,
                    post_code,
                    metadata,
                    should_change,
                    changed_expressions,
                )
                key = "changed_candidates" if should_change else "unchanged_candidates"
                expr_strings = [x.expr for x in expr_list.expressions]
                instance_result[key] = expr_strings
                if should_change:
                    changed_expressions = expr_strings
            instance_result.update(metadata)
            instance_result["function_code_before_patch"] = remove_docstrings(pre_code)
            return instance_result
        except Exception as e:
            print(
                "process_agent crashed for agent=%s | %s: %s %s",
                agent,
                instance_id,
                type(e).__name__,
                e,
            )
            return None
    
    with ThreadPoolExecutor(max_workers=10) as executor:
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
    import time

    start = time.time()

    STEP1_PATH = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/step1-filtered.json"
    STEP2_GOLD_PATH = os.path.join("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step", "step2.gold.json")
    step1 = read_json(STEP1_PATH)
    results = {}
    instance_ids = get_instance_ids(["all"])
    agents_to_process = AGENTS.copy()
    
    if os.path.exists(STEP2_GOLD_PATH):
        agents_to_process.remove("gold")

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, step1, agent, instance_ids): agent
            for agent in agents_to_process
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
    
    if "gold" in results:
        with open(STEP2_GOLD_PATH, "w") as f:
            json.dump({"gold": results["gold"]}, f, indent=2)
        print(
            "Saved step2 gold results to %s",
            STEP2_GOLD_PATH,
        )
        del results["gold"]
    
    with open(os.path.join("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step", "step2.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(
        "Saved step2 results to %s",
        "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/step2.json",
    )

    end = time.time()
    print("Execution time: %.2f seconds", end - start)
