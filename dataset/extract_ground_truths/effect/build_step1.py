# Build ground truth for effect
# Step 0. Run tracer with agent patches to collect execution traces.
# This should be done outside of this script.
# Step 1. Extract locations of divergent lines, state differences;
# and fallback if no divergence is found.
import os
import json
import signal

from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm.auto import tqdm

from dataset.extract_ground_truths.effect import get_divergent_lines
from execution.util import get_instance_ids
from tracer.serializer import serialize

EXTRA_LONG_TIMEOUT = {
    'django__django-14500': 600,
    'django__django-16667': 600,
    'pylint-dev__pylint-6903': 600,
    'pylint-dev__pylint-7080': 600,
    'sphinx-doc__sphinx-9230': 600,
    'sympy__sympy-17655': 600,
}

ADHOC_TEST_ID = {
    ("20250720_Lingxi-v1.5_claude-4-sonnet-20250514", "sympy__sympy-17655"): 1,
}

def _process_instance(instance_id, agent, total_choices, depth_threshold, timeout=300):
    def _timeout_handler(signum, frame):
        raise TimeoutError()
    try:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(EXTRA_LONG_TIMEOUT.get(instance_id, timeout))
        test_id = 0
        if (agent, instance_id) in ADHOC_TEST_ID:
            test_id = ADHOC_TEST_ID[(agent, instance_id)]
        while True:
            try:
                result = get_divergent_lines.main(
                    instance_id,
                    agent=agent,
                    test_id=test_id,
                    total_choices=total_choices, 
                    depth_threshold=depth_threshold
                )
            except IndexError:
                result = {} # fallback to gold
                break
            except AssertionError as e:
                test_id += 1
                continue
            if result:
                break
            test_id += 1
        return serialize(result)
    except FileNotFoundError:
        return {} # fallback to gold
    except TimeoutError:
        print(f"Timeout for {instance_id} with agent {agent}", flush=True)
        return None
    except Exception as e:
        import traceback
        print(f"Error for {instance_id} with agent {agent}: {e}", flush=True)
        traceback.print_exc()
        return None
    finally:
        signal.alarm(0)

def process_agent(agent, instance_ids, total_choices, depth_threshold, max_workers=10):
    results = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_instance, instance_id, agent, total_choices, depth_threshold): instance_id
            for instance_id in instance_ids
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc=agent):
            instance_id = futures[future]
            results[instance_id] = future.result()

    return results

if __name__ == "__main__":
    # ------------ SCRIPT PARAMETERS ------------ #
    AGENTS = [
        "20250603_Refact_Agent_claude-4-sonnet",
        "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
        "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
        "20250928_trae_doubao_seed_code",
        "20250807_mini-v1.7.0_gpt-5-mini",
        "gold",
    ]
    OUTPUT_DIR = os.path.join("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step", f"step1.json")
    TOTAL_CHOICES = 4
    DEPTH_THRESHOLD = 3
    # ------------------------------------------- #

    results = {}
    instance_ids = get_instance_ids(["all"])
    with ProcessPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, agent, instance_ids, TOTAL_CHOICES, DEPTH_THRESHOLD): agent
            for agent in AGENTS if agent
        }
        for future in as_completed(futures):
            agent = futures[future]
            results[agent] = future.result()
    with open(OUTPUT_DIR, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved step1 results to {OUTPUT_DIR}")