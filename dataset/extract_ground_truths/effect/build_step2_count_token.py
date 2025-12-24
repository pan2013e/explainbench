# Build ground truth for effect
# Step 2 (token counting). Construct prompts for step 2 and record token usage
# per instance without doing inference.
import argparse
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import tiktoken
from tqdm.auto import tqdm

from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect.build_step2 import (
    get_agent_patch,
    get_simple_function_name,
)
from dataset.extract_ground_truths.effect.infer_expression import (
    TEMPLATE_CHANGED,
    TEMPLATE_UNCHANGED,
    extract_seed_exp,
)
from dataset.extract_ground_truths.effect.source_util import get_function_code

logger = logging.getLogger(__name__)

def build_fn_code(pre_code, post_code):
    if pre_code == post_code:
        return pre_code
    return f"# Before Patch:\n{pre_code}\n\n# After Patch:\n{post_code}"

def build_statement(pre_stmt, post_stmt, pre_type, post_type):
    def exc_tag(event_type):
        if event_type == "Exception":
            return " (crashed here)"
        return " (normally executed)"
    if pre_stmt == post_stmt:
        return pre_stmt
    return f"# Before Patch:\n{pre_stmt}{exc_tag(pre_type)}\n\n# After Patch:\n{post_stmt}{exc_tag(post_type)}"

def build_prompt_inputs(pre_code, post_code, metadata):
    return {
        "code": build_fn_code(pre_code, post_code),
        "line": build_statement(
            metadata["buggy_statement"],
            metadata["patched_statement"],
            metadata["buggy_event_type"],
            metadata["patched_event_type"],
        ),
        "diff": metadata["diff"],
        "before": metadata["buggy_variables"],
        "after": metadata["patched_variables"],
    }


def read_json(path):
    with open(os.path.join(path), "r") as f:
        return json.load(f)


def _get_encoder(model, encoding_name=None):
    if encoding_name:
        return tiktoken.get_encoding(encoding_name)
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def build_prompt(prompt_inputs, should_change, changed_expressions):
    if should_change:
        return TEMPLATE_CHANGED.format(
            code=prompt_inputs["code"],
            line=prompt_inputs["line"],
            diff=prompt_inputs["diff"],
            before=prompt_inputs["before"],
            after=prompt_inputs["after"],
            n_output=10,
            seed_expression=extract_seed_exp(prompt_inputs["diff"]),
        )
    return TEMPLATE_UNCHANGED.format(
        code=prompt_inputs["code"],
        line=prompt_inputs["line"],
        diff=prompt_inputs["diff"],
        before=prompt_inputs["before"],
        after=prompt_inputs["after"],
        n_output=10,
        changed_expressions=changed_expressions if changed_expressions else "",
    )


def count_prompt_tokens(encoder, pre_code, post_code, metadata):
    prompt_inputs = build_prompt_inputs(pre_code, post_code, metadata)
    changed_prompt = build_prompt(prompt_inputs, True, None)
    unchanged_prompt = build_prompt(prompt_inputs, False, "")
    return len(encoder.encode(changed_prompt)) + len(encoder.encode(unchanged_prompt))


def process_agent(agent_data, agent, instance_ids, encoder, max_workers):
    results = {}

    def process_instance(instance_id):
        try:
            metadata = agent_data[agent][instance_id]
            if metadata is None:
                print(
                    "metadata not found due to errors for agent={} | instance_id={}".format(
                        agent,
                        instance_id,
                    )
                )
                return None
            if metadata == {}:
                print(
                    "no behavior delta for agent={} | instance_id={}, need to fallback to gold in step 3".format(
                        agent,
                        instance_id,
                    )
                )
                return 0
            if metadata.get("choices"):
                print(
                    "exception vs return None for agent={} | instance_id={}, fallback to reachability question in step 4".format(
                        agent,
                        instance_id,
                    )
                )
                return 0

            pre_code, post_code = get_function_code(
                instance_id,
                metadata["file_path"],
                get_simple_function_name(metadata),
                patch=get_agent_patch(agent, instance_id),
                line_hint=(metadata["buggy_lineno"], metadata["patched_lineno"]),
            )

            return count_prompt_tokens(encoder, pre_code, post_code, metadata)
        except Exception as e:
            print(
                "process_agent crashed for agent={} | {}: {} {}".format(
                    agent,
                    instance_id,
                    type(e).__name__,
                    e,
                )
            )
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_instance, instance_id): instance_id
            for instance_id in instance_ids
        }
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc=f"Processing agent {agent}",
        ):
            instance_id = futures[future]
            result = future.result()
            if result is not None:
                results[instance_id] = result
    return results


def main():
    AGENTS = [
        "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
        "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
        "20250612_trae",
        "gold",
    ]
    parser = argparse.ArgumentParser(
        description="Count tiktoken prompt tokens for step2 without inference."
    )
    parser.add_argument(
        "--step1-path",
        default="/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-2/step1.json",
    )
    parser.add_argument(
        "--output-path",
        default="/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-2/step2.token.json",
    )
    parser.add_argument("--model", default="gpt-5.1-codex-mini")
    parser.add_argument("--encoding", default=None)
    parser.add_argument("--max-agent-workers", type=int, default=10)
    parser.add_argument(
        "--max-instance-workers",
        type=int,
        default=30 // min(10, len(AGENTS)),
    )
    args = parser.parse_args()

    start = time.time()

    step1 = read_json(args.step1_path)
    results = {}
    instance_ids = get_instance_ids(["all"])
    agents_to_process = AGENTS.copy()

    encoder = _get_encoder(args.model, args.encoding)

    with ThreadPoolExecutor(max_workers=args.max_agent_workers) as executor:
        futures = {
            executor.submit(
                process_agent,
                step1,
                agent,
                instance_ids,
                encoder,
                args.max_instance_workers,
            ): agent
            for agent in agents_to_process
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()

    with open(args.output_path, "w") as f:
        json.dump(results, f, indent=2)
    print("Saved step2 token results to {}".format(args.output_path))

    end = time.time()
    print("Execution time: {:.2f} seconds".format(end - start))


if __name__ == "__main__":
    main()
