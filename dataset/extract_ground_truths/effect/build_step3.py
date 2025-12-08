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

def read_step2_results():
    with open(os.path.join(DIR, "tmp/step2.json"), "r") as f:
        return json.load(f)

@backoff.on_exception(backoff.constant, Exception, max_tries=5)
def validate_expression(expr, metadata):
    try:
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
        )
        return expr
    except:
        return None

def process_agent(data, agent, instance_ids):
    results = {}
    for key in ("changed_candidates", "unchanged_candidates"):
        output_key = "valid_changed_expressions" if key == "changed_candidates" else "valid_unchanged_expressions"
        for instance_id in instance_ids:
            metadata = data[agent][instance_id]
            if metadata is None:
                results[instance_id] = None
                continue
            expression_candidates =  metadata[key]
            valid_exprs = []
            for expr in enumerate(expression_candidates):            
                valid_expr = validate_expression(
                    expr,
                    metadata,
                )
                if valid_expr:
                    valid_exprs.append(valid_expr.exp)
            results[instance_id] = {
                output_key: valid_exprs
                **metadata
            }
    return results

if __name__ == "__main__":
    step2 = read_step2_results()
    results = {}
    instance_ids = get_instance_ids(["astropy__astropy-12907"])
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, step2, agent, instance_ids): agent
            for agent in AGENTS if agent
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
    with open(os.path.join(DIR, "tmp/step2.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("Saved step2 results to tmp/step2.json")