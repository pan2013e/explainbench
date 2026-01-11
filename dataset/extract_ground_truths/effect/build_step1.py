# Build ground truth for effect
# Step 0. Run tracer with agent patches to collect execution traces.
# This should be done outside of this script.
# Step 1. Extract locations of divergent lines, state differences;
# and fallback if no divergence is found.
import os
import json
import signal

from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from tqdm.auto import tqdm

from dataset.extract_ground_truths.effect import get_divergent_lines
from execution.util import get_instance_ids

EXTRA_LONG_TIMEOUT = {
    'django__django-11999': 2400,
    'django__django-13401': 2400,
    'django__django-13820': 1800,
    'django__django-14500': 1200,
    'django__django-14855': 2400,
    'django__django-15503': 1800,
    'django__django-15563': 600,
    'django__django-16527': 600,
    'django__django-16667': 1200,
    'pylint-dev__pylint-6386': 1800,
    'pylint-dev__pylint-7080': 600,
    'sphinx-doc__sphinx-8551': 600,
    'sphinx-doc__sphinx-9230': 1200,
    'sphinx-doc__sphinx-9698': 1800,
    'sphinx-doc__sphinx-9673': 1200,
    'sympy__sympy-17655': 600,
    'sympy__sympy-20428': 1800,
}

ADHOC_TEST_ID = {
    "sympy__sympy-17655": 1,
}

def _process_instance(instance_id, agent, total_choices, depth_threshold, timeout=300):
    def _timeout_handler(signum, frame):
        raise TimeoutError()
    try:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(EXTRA_LONG_TIMEOUT.get(instance_id, timeout))
        test_id = ADHOC_TEST_ID.get(instance_id, 0)
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
        return result
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
            try:
                results[instance_id] = future.result()
            except BrokenProcessPool:
                print(f"Process unexpectedly terminated for {instance_id} with agent {agent}. Possibly by OOM killer.", flush=True)
                results[instance_id] = None

    return results

def _type_stub(value):
    if isinstance(value, dict):
        keys = [x for x in value.keys() if not x.startswith("py/")]
        if "py/object" in value and keys:
            return {"py/object": value["py/object"], "__dir__": keys}
        if "py/type" in value and keys:
            return value
        return {"py/object": "builtins.dict"}
    if isinstance(value, list):
        return {"py/object": "builtins.list", "len": len(value)}
    raise ValueError(f"Unexpected type {type(value)}")

def _simplify(value, max_depth: int, depth: int):
    if isinstance(value, dict):
        if depth > max_depth:
            return _type_stub(value)
        return {k: _simplify(v, max_depth, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if depth > max_depth:
            return _type_stub(value)
        return [_simplify(v, max_depth, depth + 1) for v in value]
    return value

def simplify_params(data, max_depth: int) -> None:
    for agent_data in data.values():
        for metadata in agent_data.values():
            if metadata:
                for key in (
                    "buggy_function_param",
                    "buggy_variables",
                    "patched_variables",
                ):
                    if key in metadata:
                        metadata[key] = _simplify(metadata[key], max_depth, depth=0)

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
    DO_SIMPLIFICATION = False
    SIMPLICIFY_MAX_DEPTH = 4
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
    if DO_SIMPLIFICATION:
        simplify_params(results, SIMPLICIFY_MAX_DEPTH)
    with open(OUTPUT_DIR, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved step1 results to {OUTPUT_DIR}")
