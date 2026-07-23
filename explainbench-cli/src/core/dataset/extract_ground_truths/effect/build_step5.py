import os
import io
import json
import warnings
import argparse

DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE_DIR = os.path.join(DIR, "../../../logs/run_evaluation")
DEFAULT_CONTEXT_DIR = os.path.join(DIR, "../../context")
DEFAULT_GROUND_TRUTH_DIR = os.path.join(DIR, "../../ground_truths")
DEFAULT_AGENTS = [
    "20250603_Refact_Agent_claude-4-sonnet",
    "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
    "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
    "20250928_trae_doubao_seed_code",
    "20250807_mini-v1.7.0_gpt-5-mini",
    "20251127_openhands_claude-opus-4-5",
    "openhands_gpt-5-mini",
    "openhands_minimax-m2.5",
]

def read_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def get_function_input(metadata, max_characters=20000):
    output = io.StringIO()
    pre = metadata['buggy_function_param']
    print(pre, file=output)
    contents = output.getvalue()
    output.close()
    if len(contents) > max_characters:
        contents = contents[:max_characters] + " ...(truncated)"
    return contents

def get_ctx_and_gt(data, parameter_max_characters=20000):
    ctx = {
        'function_code_before_patch': data['function_code_before_patch'],
        'function_parameters_before_patch': get_function_input(
            data, parameter_max_characters
        ),
        'line': data['location'],
        'choices': data['choices'],
        'before_or_after': data['before_or_after'],
    }
    gt = {
        'answer': data['answer']
    }
    return ctx, gt

def dump_local_effect_ctx_and_gt(
    agents,
    step4_path,
    ctx_save_dir,
    gt_save_dir,
    instance_ids=None,
    parameter_max_characters=20000,
):
    if not os.path.exists(step4_path):
        warnings.warn(f"Step4 path does not exist: {step4_path}")
        return
    step4 = read_json(step4_path)
    os.makedirs(ctx_save_dir, exist_ok=True)
    os.makedirs(gt_save_dir, exist_ok=True)
    for agent in agents:
        if agent not in step4:
            warnings.warn(f"Agent {agent} not found in {step4_path}")
            continue
        agent_data = step4[agent]
        ctx_results = {}
        gt_results = {}
        for instance_id, data in agent_data.items():
            if instance_ids is not None and instance_id not in instance_ids:
                continue
            ctx, gt = get_ctx_and_gt(data, parameter_max_characters)
            ctx_results[instance_id] = ctx
            gt_results[instance_id] = gt
        with open(os.path.join(ctx_save_dir, f"local_effect__{agent}.json"), "w") as f:
            json.dump(ctx_results, f, indent=2)
            print(f"Saved {agent} context for local effect")
        with open(os.path.join(gt_save_dir, f"local_effect__{agent}.json"), "w") as f:
            json.dump(gt_results, f, indent=2)
            print(f"Saved {agent} ground truth for local effect")

def dump_local_intent_ctx_and_gt(
    step4_path,
    ctx_save_dir,
    gt_save_dir,
    instance_ids=None,
    parameter_max_characters=20000,
):
    if not os.path.exists(step4_path):
        warnings.warn(f"Step4 path does not exist: {step4_path}")
        return
    step4 = read_json(step4_path)
    if "gold" not in step4:
        warnings.warn(f"Gold patch data not found in {step4_path}")
        return
    step4 = step4["gold"]
    os.makedirs(ctx_save_dir, exist_ok=True)
    os.makedirs(gt_save_dir, exist_ok=True)
    ctx_results = {}
    gt_results = {}
    for instance_id, data in step4.items():
        if instance_ids is not None and instance_id not in instance_ids:
            continue
        ctx, gt = get_ctx_and_gt(data, parameter_max_characters)
        ctx_results[instance_id] = ctx
        gt_results[instance_id] = gt
    with open(os.path.join(ctx_save_dir, "local_intent.json"), "w") as f:
        json.dump(ctx_results, f, indent=2)
        print("Saved context for local intent")
    with open(os.path.join(gt_save_dir, "local_intent.json"), "w") as f:
        json.dump(gt_results, f, indent=2)
        print("Saved ground truth for local intent")

def build_parser():
    parser = argparse.ArgumentParser(
        description="Export local question context and ground-truth JSON files."
    )
    agents = parser.add_mutually_exclusive_group()
    agents.add_argument(
        "--agent",
        action="append",
        help="Effect agent to export; repeat to export multiple agents.",
    )
    agents.add_argument("--agents", nargs="+", help="Effect agents to export.")
    parser.add_argument(
        "--kind",
        choices=("effect", "intent", "both"),
        default="both",
    )
    parser.add_argument(
        "--instance-ids",
        "--instance_ids",
        nargs="+",
        help="Optional subset of instances to export.",
    )
    parser.add_argument(
        "--effect-step4-path",
        default=os.path.join(DEFAULT_BASE_DIR, "output_per_step", "step4.json"),
    )
    parser.add_argument(
        "--intent-step4-path",
        default=os.path.join(
            DEFAULT_BASE_DIR, "output_per_step", "step4.intent.json"
        ),
    )
    parser.add_argument("--context-dir", default=DEFAULT_CONTEXT_DIR)
    parser.add_argument(
        "--ground-truth-dir",
        default=DEFAULT_GROUND_TRUTH_DIR,
    )
    parser.add_argument(
        "--parameter-max-characters",
        type=int,
        default=20000,
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    selected_agents = args.agent or args.agents or DEFAULT_AGENTS
    selected_instances = (
        set(args.instance_ids)
        if args.instance_ids is not None and args.instance_ids != ["all"]
        else None
    )
    if args.kind in {"effect", "both"}:
        dump_local_effect_ctx_and_gt(
            selected_agents,
            args.effect_step4_path,
            args.context_dir,
            args.ground_truth_dir,
            selected_instances,
            args.parameter_max_characters,
        )
    if args.kind in {"intent", "both"}:
        dump_local_intent_ctx_and_gt(
            args.intent_step4_path,
            args.context_dir,
            args.ground_truth_dir,
            selected_instances,
            args.parameter_max_characters,
        )


if __name__ == "__main__":
    main()
