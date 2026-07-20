import os
import json
import warnings

from explainbench.question_builders.local.stages.export_question_artifacts import (
    format_function_parameters,
)

def read_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def get_function_input(metadata):
    return format_function_parameters(metadata['buggy_function_param'])

def get_ctx_and_gt(data):
    ctx = {
        'function_code_before_patch': data['function_code_before_patch'],
        'function_parameters_before_patch': get_function_input(data),
        'line': data['location'],
        'choices': data['choices'],
        'before_or_after': data['before_or_after'],
    }
    gt = {
        'answer': data['answer']
    }
    return ctx, gt

def dump_local_effect_ctx_and_gt(agents, step4_path, ctx_save_dir, gt_save_dir):
    if not os.path.exists(step4_path):
        warnings.warn(f"Step4 path does not exist: {step4_path}")
        return
    step4 = read_json(step4_path)
    for agent in agents:
        if agent not in step4:
            warnings.warn(f"Agent {agent} not found in {step4_path}")
            continue
        agent_data = step4[agent]
        ctx_results = {}
        gt_results = {}
        for instance_id, data in agent_data.items():
            ctx, gt = get_ctx_and_gt(data)
            ctx_results[instance_id] = ctx
            gt_results[instance_id] = gt
        with open(os.path.join(ctx_save_dir, f"local_effect__{agent}.json"), "w") as f:
            json.dump(ctx_results, f, indent=2)
            print(f"Saved {agent} context for local effect")
        with open(os.path.join(gt_save_dir, f"local_effect__{agent}.json"), "w") as f:
            json.dump(gt_results, f, indent=2)
            print(f"Saved {agent} ground truth for local effect")

def dump_local_intent_ctx_and_gt(step4_path, ctx_save_dir, gt_save_dir):
    if not os.path.exists(step4_path):
        warnings.warn(f"Step4 path does not exist: {step4_path}")
        return
    step4 = read_json(step4_path)
    if "gold" not in step4:
        warnings.warn(f"Gold patch data not found in {step4_path}")
        return
    step4 = step4["gold"]
    ctx_results = {}
    gt_results = {}
    for instance_id, data in step4.items():
        ctx, gt = get_ctx_and_gt(data)
        ctx_results[instance_id] = ctx
        gt_results[instance_id] = gt
    with open(os.path.join(ctx_save_dir, "local_intent.json"), "w") as f:
        json.dump(ctx_results, f, indent=2)
        print("Saved context for local intent")
    with open(os.path.join(gt_save_dir, "local_intent.json"), "w") as f:
        json.dump(gt_results, f, indent=2)
        print("Saved ground truth for local intent")

if __name__ == "__main__":
    BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../logs/run_evaluation")
    CTX_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../context")
    GT_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../ground_truths")
    if not os.path.exists(CTX_SAVE_DIR):
        os.makedirs(CTX_SAVE_DIR, exist_ok=True)
    if not os.path.exists(GT_SAVE_DIR):
        os.makedirs(GT_SAVE_DIR, exist_ok=True)
    AGENTS = [
        "20250603_Refact_Agent_claude-4-sonnet",
        "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
        "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
        "20250928_trae_doubao_seed_code",
        "20250807_mini-v1.7.0_gpt-5-mini",
        "20251127_openhands_claude-opus-4-5",
        "openhands_gpt-5-mini",
        "openhands_minimax-m2.5"
    ]
    dump_local_effect_ctx_and_gt(
        AGENTS,
        os.path.join(BASE_DIR, "output_per_step", "step4.json"),
        CTX_SAVE_DIR,
        GT_SAVE_DIR,
    )
    dump_local_intent_ctx_and_gt(
        os.path.join(BASE_DIR, "output_per_step", "step4.intent.json"),
        CTX_SAVE_DIR,
        GT_SAVE_DIR,
    )
