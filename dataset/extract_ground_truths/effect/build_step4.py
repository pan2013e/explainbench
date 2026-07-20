import os
import json
import random
import argparse

from tqdm.auto import tqdm
from typing import Callable, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

random.seed(42)
MMR_LAMBDA = 0.7

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
]

def read_json(input_path):
    with open(input_path, "r") as f:
        return json.load(f)

def intersect_instance_ids(step3_data, agents):
    id_sets = []
    for agent in agents:
        instances = step3_data.get(agent, {})
        if isinstance(instances, dict):
            id_sets.append(set(instances.keys()))
    if not id_sets:
        return set()
    intersection = set.intersection(*id_sets)
    return intersection

def meets_min_pool(metadata, min_changed=1, min_unchanged=3):
    if not isinstance(metadata, dict):
        return False
    if metadata.get("choices") is not None:
        return True
    valid_changed = metadata.get("valid_changed_expressions") or []
    valid_unchanged = metadata.get("valid_unchanged_expressions") or []
    return len(valid_changed) >= min_changed and len(valid_unchanged) >= min_unchanged

def sampler_function(pool: List[str], k: int) -> List[str]:
    k = min(k, len(pool))
    return random.sample(list(pool), k=k)

def levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (0 if ca == cb else 1)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]

def normalized_similarity(a: str, b: str) -> float:
    max_len = max(len(a), len(b), 1)
    return 1.0 - (levenshtein_distance(a, b) / max_len)

def avg_similarity(item: str, pool: List[str]) -> float:
    if not pool:
        return 0.0
    return sum(normalized_similarity(item, other) for other in pool) / len(pool)

def max_similarity(item: str, pool: List[str]) -> float:
    if not pool:
        return 0.0
    return max(normalized_similarity(item, other) for other in pool)

def select_hard_anchors(correct_pool: List[str], incorrect_pool: List[str], k: int) -> List[str]:
    if k <= 0 or not correct_pool:
        return []
    scored = [
        (avg_similarity(c, incorrect_pool), c)
        for c in correct_pool
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]

def select_distractors_mmr(
    incorrect_pool: List[str],
    anchors: List[str],
    k: int,
    lambda_weight: float,
) -> List[str]:
    if k <= 0 or not incorrect_pool:
        return []
    selected: List[str] = []
    remaining = list(incorrect_pool)
    while remaining and len(selected) < k:
        best_idx = 0
        best_score = None
        for idx, candidate in enumerate(remaining):
            relevance = max_similarity(candidate, anchors)
            diversity_penalty = max_similarity(candidate, selected)
            score = (lambda_weight * relevance) - ((1.0 - lambda_weight) * diversity_penalty)
            if best_score is None or score > best_score:
                best_score = score
                best_idx = idx
        selected.append(remaining.pop(best_idx))
    return selected

def build_choices_and_answer(
    n_correct: int,
    n_incorrect: int,
    correct_pool: List[str],
    incorrect_pool: List[str],
    sampler_function: Callable,
    add_none_of_the_above: bool = True,
    add_cannot_infer: bool = True,
    labels: str = "abcdefghijklmnopqrstuvwxyz",
    is_fallback_to_gold: bool = False,
) -> Tuple[List[str], List[str]]:
    if is_fallback_to_gold:
        incorrect_pool = incorrect_pool + correct_pool
    
    sampled_correct = select_hard_anchors(correct_pool, incorrect_pool, n_correct)
    sampled_incorrect = select_distractors_mmr(
        incorrect_pool, sampled_correct, n_incorrect, lambda_weight=MMR_LAMBDA
    )
    if len(sampled_correct) < n_correct:
        remaining = [c for c in correct_pool if c not in sampled_correct]
        sampled_correct += sampler_function(remaining, n_correct - len(sampled_correct))
    if len(sampled_incorrect) < n_incorrect:
        remaining = [i for i in incorrect_pool if i not in sampled_incorrect]
        sampled_incorrect += sampler_function(remaining, n_incorrect - len(sampled_incorrect))

    choices: List[str] = list(sampled_correct) + list(sampled_incorrect)
    is_correct: List[bool] = [True] * len(sampled_correct) + [False] * len(
        sampled_incorrect
    )

    combined = list(zip(choices, is_correct))
    random.shuffle(combined)
    if combined:
        choices, is_correct = map(list, zip(*combined))
    else:
        choices, is_correct = [], []

    if add_none_of_the_above:
        none_option: str = "The patch has no effect and none of the above expressions change in value"
        has_any_correct = any(is_correct)
        choices.append(none_option)
        is_correct.append(not has_any_correct)
    
    if add_cannot_infer:
        cannot_infer_option = "Cannot be answered by the explanation alone"
        choices.append(cannot_infer_option)
        is_correct.append(False)

    answer = [labels[i] for i, flag in enumerate(is_correct) if flag]
    return choices, answer

def process_agent(data, agent, instance_ids, n_correct, n_incorrect, is_prepare_intent):
    results = {}
    for instance_id in instance_ids:
        try:
            metadata = data[agent][instance_id]
            if metadata is None:
                results[instance_id] = None
                continue

            correct_pool = metadata["valid_changed_expressions"]
            incorrect_pool = metadata["valid_unchanged_expressions"]

            use_n_correct = n_correct
            use_n_incorrect = n_incorrect
            if metadata.get("is_fallback_to_gold"):
                # Gold fallback instances should only surface incorrect options.
                use_n_incorrect = n_correct + n_incorrect
                use_n_correct = 0

            choices, answer = build_choices_and_answer(
                n_correct=use_n_correct,
                n_incorrect=use_n_incorrect,
                correct_pool=correct_pool,
                incorrect_pool=incorrect_pool,
                sampler_function=sampler_function,
                add_none_of_the_above=not is_prepare_intent,
                is_fallback_to_gold=metadata.get("is_fallback_to_gold", False),
            )

            metadata.pop("valid_changed_expressions", None)
            metadata.pop("valid_unchanged_expressions", None)
            metadata.pop("prompt_length_chars", None)
            metadata.pop("changed_candidates", None)
            metadata.pop("unchanged_candidates", None)
            results[instance_id] = {
                "choices": choices,
                "answer": answer,
                **metadata,
            }
        except KeyError:
            raise
        except Exception as e:
            import traceback
            print(f"Error processing {agent} {instance_id}: {e}")
            traceback.print_exc()
            continue
    return results

def build_parser():
    parser = argparse.ArgumentParser(
        description="Build local-effect answer choices from validated expressions."
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
        help="Explicit instances; defaults to the valid intersection.",
    )
    parser.add_argument("--step3-path")
    parser.add_argument("--output-path")
    parser.add_argument(
        "--prepare-intent",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--correct-choices", type=int, default=1)
    parser.add_argument("--incorrect-choices", type=int, default=3)
    parser.add_argument("--minimum-changed", type=int, default=1)
    parser.add_argument("--minimum-unchanged", type=int, default=3)
    parser.add_argument("--mmr-weight", type=float, default=0.7)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--agent-workers", type=int, default=10)
    return parser


def main(argv=None):
    global MMR_LAMBDA
    args = build_parser().parse_args(argv)
    MMR_LAMBDA = args.mmr_weight
    random.seed(args.random_seed)

    if args.prepare_intent:
        print("Running for gold patch")
        selected_agents = args.agent or args.agents or ["gold"]
        step3_path = args.step3_path or os.path.join(
            DEFAULT_BASE_DIR, "output_per_step", "step3.gold.json"
        )
        output_path = args.output_path or os.path.join(
            DEFAULT_BASE_DIR, "output_per_step", "step4.intent.json"
        )
    else:
        print("Running for RQ1 agents")
        selected_agents = args.agent or args.agents or DEFAULT_AGENTS
        step3_path = args.step3_path or os.path.join(
            DEFAULT_BASE_DIR, "output_per_step", "step3.json"
        )
        output_path = args.output_path or os.path.join(
            DEFAULT_BASE_DIR, "output_per_step", "step4.json"
        )

    step3 = read_json(step3_path)
    results = {}
    available_instance_ids = sorted(
        intersect_instance_ids(step3, selected_agents)
    )
    if args.instance_ids is None or args.instance_ids == ["all"]:
        base_instance_ids = available_instance_ids
    else:
        available = set(available_instance_ids)
        base_instance_ids = [
            instance_id
            for instance_id in args.instance_ids
            if instance_id in available
        ]
    removed_due_to_pool = []
    instance_ids = []
    for instance_id in base_instance_ids:
        failed_agents = [
            agent
            for agent in selected_agents
            if not meets_min_pool(
                step3.get(agent, {}).get(instance_id),
                min_changed=args.minimum_changed,
                min_unchanged=args.minimum_unchanged,
            )
        ]
        if failed_agents:
            removed_due_to_pool.append(instance_id)

    instance_ids = [x for x in base_instance_ids if x not in removed_due_to_pool]
    print(f"Intersection instance_ids count: {len(base_instance_ids)}")
    print(f"After min-pool filter count: {len(instance_ids)}")
    # Report per-agent removals relative to filtered step3 data.
    print("Per-agent removals vs filtered step3 (intersection pruning):")
    for agent in selected_agents:
        total_filtered = len(step3.get(agent, {}) or {})
        removed = total_filtered - len(instance_ids)
        print(f"- {agent}: filtered_total={total_filtered}, removed_by_intersection={removed}")
    with ThreadPoolExecutor(max_workers=args.agent_workers) as executor:
        futures = {
            executor.submit(
                process_agent,
                step3,
                agent,
                instance_ids,
                args.correct_choices,
                args.incorrect_choices,
                args.prepare_intent,
            ): agent
            for agent in selected_agents
            if agent and agent
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved step4 results to {output_path}")


if __name__ == "__main__":
    main()
