# Build ground truth for effect
# Step 0. Run tracer with agent patches to collect execution traces.
# This should be done outside of this script.
# Step 1. Extract locations of divergent lines, state differences;
# and fallback if no divergence is found.
import os
import json

from tqdm.auto import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
from tracer.serializer import serialize
from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect import get_divergent_lines

DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS = list(
    map(
        lambda x: x.strip(),
        open(os.path.join(DIR, "../../explanations/agents.txt")).readlines()
    )
)

def process_agent(agent, instance_ids):
    results = {}
    for instance_id in instance_ids:
        try:
            results[instance_id] = serialize(get_divergent_lines.main(instance_id, agent=agent, is_return=True))
        except FileNotFoundError:
            results[instance_id] = None
        except Exception as e:
            print(f"Error for {instance_id} with agent {agent}: {e}")
            results[instance_id] = None
    return results

if __name__ == "__main__":
    results = {}
    instance_ids = get_instance_ids(["astropy", "sympy"])
    with ProcessPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, agent, instance_ids): agent
            for agent in AGENTS if agent
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
    os.makedirs(os.path.join(DIR, "tmp"), exist_ok=True)
    with open(os.path.join(DIR, "tmp/step1.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("Saved step1 results to tmp/step1.json")