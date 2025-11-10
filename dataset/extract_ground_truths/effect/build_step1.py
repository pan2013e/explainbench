# Build ground truth for effect
# Step 1. Extract locations of divergent lines, state differences;
# and fallback if no divergence is found.
import os
import json

from tqdm.auto import tqdm
from collections import defaultdict
from dataset.extract_ground_truths.effect import get_divergent_lines
from execution.util import get_instance_ids

DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS = open(os.path.join(DIR, "../../explanations/agents.txt")).readlines()

if __name__ == "__main__":
    results = defaultdict(dict)
    for agent in AGENTS:
        agent = agent.strip()
        if not agent:
            continue
        print(f"Processing agent: {agent}")
        for instance_id in tqdm(get_instance_ids("astropy")):
            try:
                results[agent][instance_id] = get_divergent_lines.main(instance_id, agent, is_return=True)
            except FileNotFoundError:
                results[agent][instance_id] = None
    # Save results
    with open(os.path.join(DIR, "tmp/step1.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("Saved step1 results to tmp/step1.json")