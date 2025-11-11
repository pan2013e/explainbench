# Build ground truth for effect
# Step 3. Run inspector with expressions from step 2 
# and get the data as ground truth.
import os
import json

from execution.inspect import main
from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect.build_step1 import AGENTS, DIR

def read_step2_results():
    with open(os.path.join(DIR, "tmp/step2.json"), "r") as f:
        return json.load(f)

def process_agent(data, agent, instance_ids):
    results = {}
    for instance_id in instance_ids:
        metadata = data[agent][instance_id]
        exprs = metadata["expr"]
        for expr in exprs:
            main([
                "--instance_id", instance_id,
                "--agent", agent,
                "--bp-file", metadata["file_path"],
                "--pre-bp-line", str(metadata["buggy_lineno"]),
                "--post-bp-line", str(metadata["patched_lineno"]),
                "--expr", expr,
                "--pre-count", str(metadata["buggy_line_count"]),
                "--post-count", str(metadata["patched_line_count"]),
            ])
    return results

if __name__ == "__main__":
    step2 = read_step2_results()
    instance_ids = get_instance_ids("astropy")
    for agent in AGENTS:
        process_agent(step2, agent, instance_ids)
