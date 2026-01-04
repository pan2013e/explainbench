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

def read_step3_results():
    with open(
        os.path.join(
            "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-3/step3-filtered.json"
        ),
        "r",
    ) as f:
        return json.load(f)

def sampler_function(pool: List[str], k: int) -> List[str]:
    k = min(k, len(pool))
    return random.sample(list(pool), k=k)

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
    
    sampled_correct = sampler_function(correct_pool, n_correct)
    sampled_incorrect = sampler_function(incorrect_pool, n_incorrect)

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

    def idx_to_label(i):
        if i < 26:
            return string.ascii_lowercase[i]
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = string.ascii_lowercase[r] + s
        return s

    answer_labels = [idx_to_label(idx_map[hash_list(a)]) for a in answers]
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

            if len(correct_pool) < use_n_correct:
                print(
                    "> Warning: number of correct answers is < n_correct. Use len(pool)"
                )

            if len(incorrect_pool) < use_n_incorrect:
                print(
                    "> Warning: number of incorrect answers is < n_incorrect. Use len(pool)"
                )

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
                **metadata,
            }
        except KeyError:
            continue
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
    AGENTS = [
        "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
        "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
        "20250612_trae",
        "gold",
    ]
    OUTPUT_DIR = "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-3/"
    OUTPUT_JSON = "step4.json"
    # ------------------------------------------- #
    
    start_time = time.time()
    step3 = read_step3_results()
    results = {}
    instance_ids = get_instance_ids(["all"])
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
