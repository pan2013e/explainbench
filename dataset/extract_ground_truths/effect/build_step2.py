# Build ground truth for effect
# Step 2. Provide step 1 info to an LLM to infer an expression
import os
import json

from tqdm.auto import tqdm
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed

from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect import infer_expression
from dataset.extract_ground_truths.effect.build_step1 import DIR, AGENTS
from dataset.extract_ground_truths.effect.source_util import get_function_code

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
        expr_candidates = infer_expression.main(
            build_fn_code(pre_code, post_code),
            metadata["statement"],
            metadata["filtered_diff"],
            metadata["buggy_variables"],
            metadata["patched_variables"],
        )
        results[instance_id] = {
            "expr": [expr.expr for expr in expr_candidates],
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