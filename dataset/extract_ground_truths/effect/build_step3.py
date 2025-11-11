# Build ground truth for effect
# Step 3. Run inspector with expressions from step 2 
# and get the data as ground truth.
import os
import json

from concurrent.futures import ThreadPoolExecutor, as_completed

from execution.inspect import main
from execution.util import get_instance_ids, get_fail_to_pass_tests
from dataset.extract_ground_truths.effect.build_step1 import AGENTS, DIR

def read_step2_results():
    with open(os.path.join(DIR, "tmp/step2.json"), "r") as f:
        return json.load(f)

def process_agent(data, agent, instance_ids):
    for instance_id in instance_ids:
        metadata = data[agent][instance_id]
        if metadata is None:
            continue
        expr = metadata["expr"][0]
        main([
            "--instance_id", instance_id,
            "--agent", agent,
            "--bp-file", metadata["file_path"],
            "--pre-bp-line", str(metadata["buggy_lineno"]),
            "--post-bp-line", str(metadata["patched_lineno"]),
            "--expr", expr,
            "--expr-id", "0",
            "--pre-count", str(metadata["buggy_line_count"]),
            "--post-count", str(metadata["patched_line_count"]),
        ])

def process_agent_read_values(data, agent, instance_ids):
    results = {}
    for instance_id in instance_ids:
        metadata = data[agent][instance_id]
        if metadata is None:
            continue
        buggy_value, patched_value = read_inspect_values(agent, instance_id, metadata["test_id"], expr_id=0)
        results[instance_id] = {
            "buggy_value": buggy_value,
            "patched_value": patched_value,
            **metadata,
        }
    return results

def read_inspect_values(agent, instance_id, test_id, expr_id=0):
    log_dir = os.path.join(DIR, f"../../../logs/run_evaluation/inspect.{agent}.{os.getuid()}.{expr_id}/{agent}/{instance_id}")
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    buggy_path = os.path.join(log_dir, f"buggy_traces/{test_name}.jsonl")
    patched_path = os.path.join(log_dir, f"patched_traces/{test_name}.jsonl")
    with open(buggy_path, "r") as f:
        buggy_value = json.load(f)['value']
    with open(patched_path, "r") as f:
        patched_value = json.load(f)['value']
    return buggy_value, patched_value

if __name__ == "__main__":
    step2 = read_step2_results()
    results = {}
    instance_ids = get_instance_ids(["astropy__astropy-12907"])
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, step2, agent, instance_ids): agent
            for agent in AGENTS if agent
        }
        for future in as_completed(futures):
            future.result()
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent_read_values, step2, agent, instance_ids): agent
            for agent in AGENTS if agent
        }
        for future in as_completed(futures):
            agent = futures[future]
            results[agent] = future.result()
    with open(os.path.join(DIR, "tmp/step3.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("Saved step3 results to tmp/step3.json")