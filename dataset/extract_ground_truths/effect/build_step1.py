# Build ground truth for effect
# Step 0. Run tracer with agent patches to collect execution traces.
# This should be done outside of this script.
# Step 1. Extract locations of divergent lines, state differences;
# and fallback if no divergence is found.
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError
from tqdm import tqdm

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
    "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
    "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
    "20250612_trae",
    "gold",
]

def _process_instance(instance_id, agent):
    try:
        test_id = 0
        while True:
            try:
                result = get_divergent_lines.main(
                    instance_id,
                    agent=agent,
                    test_id=test_id,
                )
            except IndexError:
                result = {}
                break
            except AssertionError as e:
                print(
                    f"AssertionError for {instance_id} "
                    f"(agent={agent}, test_id={test_id}): {e}",
                    flush=True,
                )
                test_id += 1
                continue
            if result:
                break
            test_id += 1

        return instance_id, serialize(result)

    except FileNotFoundError:
        print(f"FileNotFoundError for {instance_id} with agent {agent}", flush=True)
        return instance_id, None
    except Exception as e:
        print(f"Error for {instance_id} with agent {agent}: {e}", flush=True)
        return instance_id, None

def process_agent(agent, instance_ids, timeout=300, max_workers=10):
    results = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_instance, instance_id, agent): instance_id
            for instance_id in instance_ids
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Processing agent {agent}"):
            instance_id = futures[future]
            try:
                _, result = future.result(timeout=timeout)
            except TimeoutError:
                print(f"Timeout for {instance_id} with agent {agent}", flush=True)
                result = None
            results[instance_id] = result

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
    OUTPUT_DIR = os.path.join("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step", f"step1.json")
    with open(OUTPUT_DIR, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved step1 results to {OUTPUT_DIR}")