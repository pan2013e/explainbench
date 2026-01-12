import os
import json
import time
import random
import string
import hashlib

from tqdm.auto import tqdm
from typing import Callable, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from execution.util import get_instance_ids

random.seed(42)

def read_step3_results():
    with open(
        os.path.join(
            "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/step3.json"
        ),
        "r",
    ) as f:
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
        none_option: str = "None of the above"
        has_any_correct = any(is_correct)
        choices.append(none_option)
        is_correct.append(not has_any_correct)

    answer = [labels[i] for i, flag in enumerate(is_correct) if flag]
    return choices, answer

def hash_list(x):
    s = json.dumps(x, sort_keys=True).encode("utf-8")
    return hashlib.sha256(s).hexdigest()

def shuffle_choices_and_label_answer(choices, answers, seed=None):
    rng = random.Random(seed)

    shuffled = choices[:]
    rng.shuffle(shuffled)

    idx_map = {hash_list(c): i for i, c in enumerate(shuffled)}

    def label_to_idx(label: str):
        if not isinstance(label, str) or not label:
            return None
        idx = 0
        for ch in label:
            if ch not in string.ascii_lowercase:
                return None
            idx = idx * 26 + (ord(ch) - ord("a") + 1)
        return idx - 1

    def idx_to_label(i):
        if i < 26:
            return string.ascii_lowercase[i]
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = string.ascii_lowercase[r] + s
        return s

    answer_labels = []
    missing = []
    for a in answers:
        key = hash_list(a)
        if key in idx_map:
            answer_labels.append(idx_to_label(idx_map[key]))
        else:
            missing.append(a)

    if missing:
        # REMOVE NEXT ITERATION
        label_indices = []
        for a in answers:
            idx = label_to_idx(a)
            if idx is None:
                raise KeyError(f"Answer {a!r} does not match any shuffled choice.")
            label_indices.append(idx)
        if any(i < 0 or i >= len(choices) for i in label_indices):
            raise IndexError("Answer label index out of bounds for choices list.")
        answer_labels = [
            idx_to_label(idx_map[hash_list(choices[i])]) for i in label_indices
        ]
    return shuffled, answer_labels

def process_agent(data, agent, instance_ids, n_correct, n_incorrect):
    results = {}
    for instance_id in instance_ids:
        try:
            metadata = data[agent][instance_id]
            if metadata.get("choices", None):
                shuffled_choices, answer_labels = shuffle_choices_and_label_answer(metadata["choices"], metadata["answer"], seed=42)
                shuffled_choices.append(["None of the above", [-1, -1]])
                if len(answer_labels) == 0:
                    answer_labels.append(string.ascii_lowercase[len(shuffled_choices)-1])
                metadata.update({
                    "choices": shuffled_choices,
                    "answer": answer_labels,
                    "question_type": "reachability"
                })
                results[instance_id] = metadata
                continue
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
                is_fallback_to_gold=metadata.get("is_fallback_to_gold", False),
            )

            results[instance_id] = {
                "choices": choices,
                "answer": answer,
                "question_type": "expression changes",
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


if __name__ == "__main__":
    # ------------ SCRIPT PARAMETERS ------------ #
    N_CHOICES = 4
    N_CORRECT = 1
    N_INCORRECT = N_CHOICES - N_CORRECT
    MMR_LAMBDA = 0.7
    AGENTS = [
        "20250603_Refact_Agent_claude-4-sonnet",
        "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
        "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
        "20250928_trae_doubao_seed_code",
        "20250807_mini-v1.7.0_gpt-5-mini",
        # "gold",
    ]
    OUTPUT_DIR = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/"
    OUTPUT_JSON = "step4.json"
    # ------------------------------------------- #
    
    start_time = time.time()
    step3 = read_step3_results()
    results = {}
    base_instance_ids = sorted(intersect_instance_ids(step3, AGENTS))
    removed_due_to_pool = []
    instance_ids = []
    for instance_id in base_instance_ids:
        failed_agents = [
            agent
            for agent in AGENTS
            if not meets_min_pool(step3.get(agent, {}).get(instance_id))
        ]
        if failed_agents:
            removed_due_to_pool.append(instance_id)

    instance_ids = [x for x in base_instance_ids if x not in removed_due_to_pool]
    print(f"Intersection instance_ids count: {len(base_instance_ids)}")
    print(f"After min-pool filter count: {len(instance_ids)}")
    # Report per-agent removals relative to filtered step3 data.
    print("Per-agent removals vs filtered step3 (intersection pruning):")
    for agent in AGENTS:
        total_filtered = len(step3.get(agent, {}) or {})
        removed = total_filtered - len(instance_ids)
        print(f"- {agent}: filtered_total={total_filtered}, removed_by_intersection={removed}")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(
                process_agent, step3, agent, instance_ids, N_CORRECT, N_INCORRECT
            ): agent
            for agent in AGENTS
            if agent and agent != "gold"
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()

    with open(
        os.path.join(
            OUTPUT_DIR,
            OUTPUT_JSON,
        ),
        "w",
    ) as f:
        json.dump(results, f, indent=2)
    print(f"Saved step4 results to {OUTPUT_DIR}/{OUTPUT_JSON}")

    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")
