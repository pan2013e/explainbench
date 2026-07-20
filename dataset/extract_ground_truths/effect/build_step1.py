import os
import json
import signal
import argparse

from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from tqdm.auto import tqdm

from dataset.extract_ground_truths.effect import get_divergent_lines
from execution.util import get_instance_ids
from tracer.serializer import serialize

DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE_DIR = os.path.join(DIR, "../../../logs/run_evaluation")
DEFAULT_AGENTS = [
    "20250603_Refact_Agent_claude-4-sonnet",
    "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
    "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
    "20250928_trae_doubao_seed_code",
    "20250807_mini-v1.7.0_gpt-5-mini",
    "20251127_openhands_claude-opus-4-5",
    "openhands_gpt-5-mini",
    "openhands_minimax-m2.5",
    "gold",
]

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
    'matplotlib__matplotlib-22865': 3000,
    'matplotlib__matplotlib-24637': 3000,
    'matplotlib__matplotlib-26208': 3000,
    'pylint-dev__pylint-6386': 3000,
    'pylint-dev__pylint-7080': 3000,
    'scikit-learn__scikit-learn-10844': 3000,
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

def _timeout_handler(signum, frame):
    raise TimeoutError()

def _process_instance(
    instance_id,
    agent,
    depth_threshold,
    timeout=600,
    trace_base_dir=None,
):
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
                    base_dir=trace_base_dir,
                    depth_threshold=depth_threshold,
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

def process_agent(
    agent,
    instance_ids,
    depth_threshold,
    max_workers=20,
    timeout=600,
    trace_base_dir=None,
):
    results = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _process_instance,
                instance_id,
                agent,
                depth_threshold,
                timeout,
                trace_base_dir,
            ): instance_id
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

def build_parser():
    parser = argparse.ArgumentParser(
        description="Find the first useful buggy/patched trace divergence."
    )
    agents = parser.add_mutually_exclusive_group()
    agents.add_argument(
        "--agent",
        action="append",
        help="Agent to process; repeat to process multiple agents.",
    )
    agents.add_argument("--agents", nargs="+", help="Agents to process.")
    parser.add_argument(
        "--instance-ids",
        "--instance_ids",
        nargs="+",
        default=["all"],
    )
    parser.add_argument(
        "--trace-root-template",
        help=(
            "Optional detailed-trace agent directory. May contain {agent}; "
            "otherwise the same directory is used for every selected agent."
        ),
    )
    parser.add_argument(
        "--output-path",
        default=os.path.join(DEFAULT_BASE_DIR, "output_per_step", "step1.json"),
    )
    parser.add_argument("--depth-threshold", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--instance-workers", type=int, default=20)
    parser.add_argument("--agent-workers", type=int, default=10)
    parser.add_argument(
        "--simplify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Simplify serialized variables and function parameters.",
    )
    parser.add_argument("--variable-max-depth", type=int, default=4)
    parser.add_argument("--parameter-max-depth", type=int, default=3)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    selected_agents = args.agent or args.agents or DEFAULT_AGENTS
    instance_ids = get_instance_ids(args.instance_ids)
    results = {}
    with ProcessPoolExecutor(max_workers=args.agent_workers) as executor:
        futures = {
            executor.submit(
                process_agent,
                agent,
                instance_ids,
                args.depth_threshold,
                args.instance_workers,
                args.timeout,
                (
                    args.trace_root_template.format(agent=agent)
                    if args.trace_root_template
                    else None
                ),
            ): agent
            for agent in selected_agents
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()

    if args.simplify:
        simplify_params(
            results,
            args.variable_max_depth,
            args.parameter_max_depth,
        )

    output_path = os.path.abspath(args.output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved step1 results to {output_path}")


if __name__ == "__main__":
    main()
