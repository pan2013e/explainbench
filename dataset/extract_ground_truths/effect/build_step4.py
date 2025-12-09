from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import random
import time
from typing import Callable, List, Tuple

from tqdm.auto import tqdm

from dataset.extract_ground_truths.effect.build_step1 import AGENTS, DIR
from execution.util import get_instance_ids

def read_step3_results():
    with open(os.path.join(DIR, "tmp/step3.json"), "r") as f:
        return json.load(f)

def sampler_function(pool: List[str], k: int) -> List[str]:
    # Simple sampler; adjust to your needs
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
) -> Tuple[List[str], List[str]]:
    """
    Build multiple-choice options and answer labels.

    Parameters
    ----------
    n_correct : int
        Number of correct options to sample from `correct_pool`.
    n_incorrect : int
        Number of incorrect options to sample from `incorrect_pool`.
    correct_pool : Sequence[str]
        Pool of correct answers.
    incorrect_pool : Sequence[str]
        Pool of incorrect answers.
    sampler_function : Callable
        A function that samples `k` items from a given pool.
        Signature: sampler_function(pool, k) -> list_of_items
    add_none_of_the_above : bool, default True
        If True, appends "None of the above" as an extra option, which
        will be the only correct answer if there are no other correct options.
    labels : str, default "abcdefghijklmnopqrstuvwxyz"
        Labels used for the answer keys.

    Returns
    -------
    choices : List[str]
        The list of choices after shuffling (and possible "None of the above").
    answer : List[str]
        A list of labels (e.g., ["a", "c"]) corresponding to correct choices.
    """

    # Sample from pools
    sampled_correct = sampler_function(correct_pool, n_correct)
    sampled_incorrect = sampler_function(incorrect_pool, n_incorrect)

    choices: List[T] = list(sampled_correct) + list(sampled_incorrect)
    is_correct: List[bool] = [True] * len(sampled_correct) + [False] * len(sampled_incorrect)

    # Shuffle choices and correctness flags together
    combined = list(zip(choices, is_correct))
    random.shuffle(combined)
    if combined:
        choices, is_correct = map(list, zip(*combined))
    else:
        choices, is_correct = [], []

    # Optional "None of the above" handling
    if add_none_of_the_above:
        none_option: T = "None of the above"  # type: ignore[assignment]
        has_any_correct = any(is_correct)
        choices.append(none_option)
        is_correct.append(not has_any_correct)

    # Map correct indices to letter labels
    answer = [labels[i] for i, flag in enumerate(is_correct) if flag]
    return choices, answer

def process_agent(data, agent, instance_ids, n_correct, n_incorrect):
    results = {}
    for instance_id in instance_ids:
        metadata = data[agent][instance_id]
        if metadata is None:
            results[instance_id] = None
            continue

        # Suppose you already have two pools for this instance:
        correct_pool = metadata["valid_changed_expressions"][0]
        incorrect_pool = metadata["valid_unchanged_expressions"][0]
        
        if len(correct_pool) < n_correct:
            print("> Warning: number of correct answers is < n_correct. Use len(pool)")

        if len(incorrect_pool) < n_incorrect:
            print("> Warning: number of incorrect answers is < n_incorrect. Use len(pool)")

        choices, answer = build_choices_and_answer(
            n_correct=n_correct,
            n_incorrect=n_incorrect,
            correct_pool=correct_pool,
            incorrect_pool=incorrect_pool,
            sampler_function=sampler_function,
        )

        results[instance_id] = {
            "choices": choices,
            "answer": answer,
            **metadata,
        }
    return results


if __name__ == "__main__":
    start_time = time.time()
    step3 = read_step3_results()
    N_CHOICES = 5
    N_CORRECT = 1
    N_INCORRECT = N_CHOICES - N_CORRECT
    results = {}
    list_ids = [
        "astropy__astropy-12907",
        "astropy__astropy-13453",
        "astropy__astropy-13579",
        # "astropy__astropy-14096",
        "sympy__sympy-12096",
        "sympy__sympy-12419",
        "sympy__sympy-12489",
        "sympy__sympy-13615",
    ]
    instance_ids = get_instance_ids(list_ids)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, step3, agent, instance_ids, N_CORRECT, N_INCORRECT): agent
            for agent in AGENTS if agent
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
    

    with open(os.path.join(DIR, "tmp/step4.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("Saved step4 results to tmp/step4.json")
    
    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")
