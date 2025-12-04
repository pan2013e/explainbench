# Build ground truth for effect
# Step 2. Provide step 1 info to an LLM to infer an expression,
# then inspect the expr value in buggy and patched versions
import os
import json
import random
import backoff

from tqdm.auto import tqdm
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed

from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect.build_step1 import DIR, AGENTS
from dataset.extract_ground_truths.effect.source_util import (
    get_function_code,
    remove_docstrings,
)
from dataset.extract_ground_truths.effect.infer_expression import main as infer_main

def read_step1_results():
    with open(os.path.join(DIR, "tmp/step1.json"), "r") as f:
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

@backoff.on_exception(backoff.constant, Exception, max_tries=5)
def infer_with_validation(pre_code, post_code, metadata, should_change=True, expr_id=0):
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
        should_change=should_change,
    )
    expr.validate_effect(
        metadata["instance_id"],
        metadata["agent"],
        metadata["file_path"],
        metadata["buggy_lineno"],
        metadata["patched_lineno"],
        metadata["test_id"],
        metadata["buggy_line_count"],
        metadata["patched_line_count"],
        metadata["before_or_after"],
        should_change=should_change,
        expr_id=expr_id,
    )
    return expr

def process_agent(data, agent, instance_ids):
    results = {}
    for instance_id in instance_ids:
        metadata = data[agent][instance_id]
        if metadata is None:
            results[instance_id] = None
            continue
        pre_code, post_code = get_function_code(
            instance_id,
            metadata['file_path'],
            get_simple_function_name(metadata),
            patch=get_agent_patch(agent, instance_id),
            line_hint=(metadata['buggy_lineno'], metadata['patched_lineno']),
        )
        n_choices = 5
        n_changes = 2
        _should_change = [True] * n_changes + [False] * (n_choices - n_changes)
        random.shuffle(_should_change)
        choices = []
        for expr_id, should_change in enumerate(_should_change):
            choice = infer_with_validation(pre_code, post_code, metadata, should_change=should_change, expr_id=expr_id).expr
            choices.append(choice)
        choices.append('None of the above')
        labels = 'abcdefghijklmnopqrstuvwxyz'
        answer = [labels[i] for i, should_change in enumerate(_should_change) if should_change]
        if not answer:
            fallback_idx = len(choices) - 1
            answer = [labels[fallback_idx]]
        results[instance_id] = {
            "choices": choices,
            "answer": answer,
            "function_code_before_patch": remove_docstrings(pre_code),
            **metadata
        }
    return results

if __name__ == "__main__":
    step1 = read_step1_results()
    results = {}
    instance_ids = get_instance_ids(["astropy__astropy-12907"])
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, step1, agent, instance_ids): agent
            for agent in AGENTS if agent
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
    with open(os.path.join(DIR, "tmp/step2.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("Saved step2 results to tmp/step2.json")