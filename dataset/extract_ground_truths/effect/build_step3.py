# Build ground truth for effect
# Step 2. Provide step 1 info to an LLM to infer an expression,
# then inspect the expr value in buggy and patched versions
import os
import json
import random
import backoff
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from tqdm.auto import tqdm
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed

from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect.build_step1 import DIR, AGENTS
from dataset.extract_ground_truths.effect.source_util import (
    get_function_code,
    remove_docstrings,
)
from dataset.extract_ground_truths.effect.infer_expression import ExpressionList, Expression
from execution.inspect import main as inspect_main
from tracer.inspector import encode_expr_list

def read_step2_results():
    with open(os.path.join(DIR, "tmp/step2.json"), "r") as f:
        return json.load(f)

def execute_candidate_expressions(
            expression_candidates: list,
            instance_id: str,
            agent: str,
            file_path: str,
            buggy_lineno: int,
            patched_lineno: int,
            test_id: int,
            buggy_line_count: int,
            patched_line_count: int,
            before_or_after: str,
            should_change=True,
            expr_id=0,
        ):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        inspect_main([
            "--instance_id", instance_id,
            "--agent", agent,
            "--bp-file", file_path,
            "--pre-bp-line", str(buggy_lineno),
            "--post-bp-line", str(patched_lineno),
            "--expr", encode_expr_list(expression_candidates),
            "--expr-id", str(expr_id),
            "--pre-count", str(buggy_line_count),
            "--post-count", str(patched_line_count),
            "--inspector-mode", before_or_after,
        ])

def process_agent(data, agent, instance_ids):
    results = {}
    for key in ("changed_candidates", "unchanged_candidates"):
        output_key = "valid_changed_expressions" if key == "changed_candidates" else "valid_unchanged_expressions"
        for instance_id in instance_ids:
            metadata = data[agent][instance_id]
            if metadata is None:
                results[instance_id] = None
                continue
            expression_candidates = metadata[key] 
            execute_candidate_expressions(
                    expression_candidates,
                    metadata["instance_id"],
                    metadata["agent"],
                    metadata["file_path"],
                    metadata["buggy_lineno"],
                    metadata["patched_lineno"],
                    metadata["test_id"],
                    metadata["buggy_line_count"],
                    metadata["patched_line_count"],
                    metadata["before_or_after"],                
                )
            breakpoint()
            
    #             if valid_expr:
    #                 valid_exprs.append(valid_expr.expr)
    #         results[instance_id] = {
    #             output_key: valid_exprs,
    #             **metadata
    #         }
    # return results

if __name__ == "__main__":
    step2 = read_step2_results()
    results = {}
    instance_ids = get_instance_ids(["astropy__astropy-12907"])
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_agent, step2, agent, instance_ids): agent
            for agent in AGENTS if agent
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            agent = futures[future]
            results[agent] = future.result()
    with open(os.path.join(DIR, "tmp/step3.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("Saved step2 results to tmp/step3.json")