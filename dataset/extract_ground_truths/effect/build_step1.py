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
from tracer.serializer import serialize

EXTRA_LONG_TIMEOUT = {
    'django__django-11999': 3000,
    'django__django-13820': 3000,
    'django__django-14500': 3000,
    'django__django-15503': 3000,
    'django__django-15563': 3000,
    'django__django-16527': 3000,
    'django__django-16333': 3000,
    'django__django-16667': 3000,
    'django__django-16938': 3000,
    'matplotlib__matplotlib-24637': 3000,
    'matplotlib__matplotlib-26208': 3000,
    'pylint-dev__pylint-6386': 3000,
    'pylint-dev__pylint-7080': 3000,
    'sphinx-doc__sphinx-8551': 3000,
    'sphinx-doc__sphinx-9230': 3000,
    'sphinx-doc__sphinx-9698': 3000,
    'sphinx-doc__sphinx-9673': 3000,
    'sympy__sympy-17655': 3000,
    'sympy__sympy-20428': 3000,
}

ADHOC_TEST_ID = {
    "sympy__sympy-17655": 1,
}

# Only effective for RQ3 agents
ADHOC_FALLBACK_REDIRECT = {
    "rq3_v1": [
        "django__django-12741",
        "django__django-14349",
        "django__django-15563",
        "matplotlib__matplotlib-21568",
        "sphinx-doc__sphinx-8269",
        "sphinx-doc__sphinx-9320",
    ],
}

def _timeout_handler(signum, frame):
    raise TimeoutError()

def _process_instance(instance_id, agent, depth_threshold, timeout=600):
    if instance_id in ADHOC_FALLBACK_REDIRECT.get(agent, []):
        return {} # fallback to gold
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

def process_agent(agent, instance_ids, depth_threshold, max_workers=20):
    results = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_instance, instance_id, agent, depth_threshold): instance_id
            for instance_id in instance_ids
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc=agent):
            instance_id = futures[future]
            try:
                results[instance_id] = serialize(future.result())
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

def simplify_params(data, var_max_depth: int, param_max_depth: int) -> None:
    for agent_data in data.values():
        for metadata in agent_data.values():
            if metadata:
                for key in (
                    "buggy_variables",
                    "patched_variables",
                ):
                    if key in metadata:
                        metadata[key] = _simplify(metadata[key], var_max_depth, depth=0)
                for key in (
                    "buggy_function_param",
                ):
                    if key in metadata:
                        metadata[key] = _simplify(metadata[key], param_max_depth, depth=0)

if __name__ == "__main__":
    # ------------ SCRIPT PARAMETERS ------------ #
    BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../logs/run_evaluation")
    RQ1_AGENTS = [
        "20250603_Refact_Agent_claude-4-sonnet",
        "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
        "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
        "20250928_trae_doubao_seed_code",
        "20250807_mini-v1.7.0_gpt-5-mini",
        "gold",
    ]
    # Assume gold has been processed in RQ1
    RQ3_AGENTS = [
        "rq3_v1",
    ]
    RUN_RQ3 = False
    if RUN_RQ3:
        print("Running RQ3")
        AGENTS = RQ3_AGENTS
        OUTPUT_PATH = os.path.join(BASE_DIR, "output_per_step_rq3", "step1.json")
    else:
        print("Running RQ1")
        AGENTS = RQ1_AGENTS
        OUTPUT_PATH = os.path.join(BASE_DIR, "output_per_step", "step1.json")
    DEPTH_THRESHOLD = 3
    DO_SIMPLIFICATION = True
    SIMPLIFY_VAR_MAX_DEPTH = 4
    SIMPLIFY_PARAM_MAX_DEPTH = 3
    FRESH_RUN = False
    # ------------------------------------------- #

    results = {}
    if os.path.exists(OUTPUT_PATH) and not FRESH_RUN:
        with open(OUTPUT_PATH, "r") as f:
            exist_agents = list(json.load(f).keys())
        OUTPUT_PATH = OUTPUT_PATH.replace(".json" ,".incremental.json")
    else:
        exist_agents = []
    
    agents_to_process = AGENTS.copy()
    agents_to_process = [agent for agent in agents_to_process if agent not in exist_agents]
    
    instance_ids = get_instance_ids(["all"])
    with ProcessPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, agent, instance_ids, DEPTH_THRESHOLD): agent for agent in agents_to_process
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()

    if DO_SIMPLIFICATION:
        simplify_params(results, SIMPLIFY_VAR_MAX_DEPTH, SIMPLIFY_PARAM_MAX_DEPTH)
    
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved step1 results to {OUTPUT_PATH}")
