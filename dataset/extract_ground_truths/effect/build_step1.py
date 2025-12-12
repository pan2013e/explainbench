# Build ground truth for effect
# Step 0. Run tracer with agent patches to collect execution traces.
# This should be done outside of this script.
# Step 1. Extract locations of divergent lines, state differences;
# and fallback if no divergence is found.
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
import signal

from tqdm.auto import tqdm

from dataset.extract_ground_truths.effect import get_divergent_lines
from execution.util import get_instance_ids
from tracer.serializer import serialize

DIR = os.path.dirname(os.path.abspath(__file__))
# AGENTS = list(
#     map(
#         lambda x: x.strip(),
#         open(os.path.join(DIR, "../../explanations/agents.txt")).readlines()
#     )
# )
AGENTS = [
    "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
    "20250612_trae",
    "gold",
]

def process_agent(agent, instance_ids):
    def _timeout_handler(signum, frame):
        raise TimeoutError("Timed out after 300 seconds")
    results = {}
    for instance_id in instance_ids:
        try:
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(300)
            results[instance_id] = serialize(get_divergent_lines.main(instance_id, agent=agent))
        except FileNotFoundError:
            results[instance_id] = None
        except Exception as e:
            print(f"Error for {instance_id} with agent {agent}: {e}", flush=True)
            results[instance_id] = None
        finally:
            signal.alarm(0)
    return results

if __name__ == "__main__":
    results = {}
    instance_ids = get_instance_ids(["all"])
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