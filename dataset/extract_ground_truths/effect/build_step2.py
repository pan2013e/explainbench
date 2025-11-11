# Build ground truth for effect
# Step 2. Provide step 1 info to an LLM to infer an expression
import os
import json

from tqdm.auto import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed

from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect import infer_expression
from dataset.extract_ground_truths.effect.build_step1 import DIR, AGENTS
from dataset.extract_ground_truths.effect.source_util import get_function_code

def read_step1_results():
    with open(os.path.join(DIR, "tmp/step1.json"), "r") as f:
        return json.load(f)
    
def process_agent(data, agent, instance_ids):
    results = {}
    for instance_id in instance_ids:
        metadata = data[agent][instance_id]
        fn_code = get_function_code(instance_id, metadata['file_path'], metadata['function_name'], line_hint=metadata['line_number'])
        expr_candidates = infer_expression.main(fn_code, metadata["statement"], metadata["buggy_variables"], metadata["patched_variables"])
        results[instance_id] = {
            "expr": [expr.expr for expr in expr_candidates],
            **metadata
        }
    return results

if __name__ == "__main__":
    step1 = read_step1_results()
    results = {}
    instance_ids = get_instance_ids("astropy")
    with ProcessPoolExecutor(max_workers=10) as executor:
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