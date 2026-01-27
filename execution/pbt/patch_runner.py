import re
import json
import argparse
from pathlib import Path
from multiprocessing import Pool
from functools import partial

import litellm
from tqdm import tqdm
from pydantic import BaseModel
from litellm import completion
from datasets import load_dataset

from execution.pbt.test_runner import evaluate_test
from execution.pbt.util import FullReproResult, REPRODUCER_LOC
from execution.pbt.pbt_util import strip_main_guard, add_hypothesis_calls

litellm._logging._disable_debugging()

SYSTEM_PROMPT = Path(__file__).parent / "e2e_option_system.txt"
SWEB_DATASET = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")

class ErrorInfo(BaseModel):
    lineno: int
    exception_type: str

class ErrorInfoList(BaseModel):
    info_list: list[ErrorInfo]

def read_swebench_pred_file(
    swebench_pred_file: Path
) -> dict[str, str]:
    pred_dict = {}
    for instance_id, pred_info in json.loads(swebench_pred_file.read_text()).items():
        instance_id = pred_info["instance_id"]
        pred_patch = pred_info["model_patch"]
        pred_dict[instance_id] = pred_patch
    return pred_dict

def _get_instance_by_suffix(suffix: str) -> list:
    dataset = SWEB_DATASET
    return [x for x in dataset if x["instance_id"].endswith(suffix)]

def normalize_pbt(pbt_source: str) -> str:
    # Strip main guard
    stripped_source = strip_main_guard(pbt_source)
    # Add hypothesis calls
    stripped_source = add_hypothesis_calls(stripped_source)
    return stripped_source

def get_pbt_info(
    pbt_file: Path
) -> dict[str, str]:
    pbt_info_list = json.loads(
        pbt_file.read_text()
    )
    pbt_dict = {
        info["instance_id"]: normalize_pbt(info["test"])
        for info in pbt_info_list
    }
    return pbt_dict

def _eval_single_instance(
    instance_id: str,
    swebench_pred_dict: dict[str, str],
    pbt_dict: dict[str, str]
) -> tuple[str, FullReproResult]:
    test_content = pbt_dict[instance_id]
    pred_patch = swebench_pred_dict.get(instance_id, "")
    for _ in range(5):
        try:
            eval_result = evaluate_test(
                instance_id = instance_id,
                test_content = test_content,
                patch = pred_patch
            )
            if eval_result.buggy_returncode == 0:
                raise ValueError(f"Buggy version did not fail for {instance_id}, retrying evaluation.")
            return instance_id, eval_result
        except Exception as e:
            pass
    raise RuntimeError(f"Failed to run evaluation for {instance_id} after 5 attempts.")

def run_pbts_on_patches(
    swebench_pred_dict: dict[str, str],
    pbt_dict: dict[str, str],
    workers: int = 4
) -> dict[str, FullReproResult]:
    results: dict[str, FullReproResult] = {}
    eval_single_instance = partial(
        _eval_single_instance,
        swebench_pred_dict = swebench_pred_dict,
        pbt_dict = pbt_dict
    )
    
    with Pool(workers) as pool:
        for instance_id, eval_result in tqdm(
            pool.imap_unordered(
                eval_single_instance,
                pbt_dict.keys()
            ),
            total = len(pbt_dict)
        ):
            results[instance_id] = eval_result
    return results

class QuestionConstructor():
    PASSED_STR = "The test passed."
    ERROR_STR_TEMPLATE = "The test failed at line {lineno} with exception: {exception}."

    @staticmethod
    def question_seed(repro_result: FullReproResult) -> dict:
        err_line_regex = re.compile(rf'File "{REPRODUCER_LOC}", line (\d+)')
        exception_regex = re.compile(r'^(.*(?:Error|Exception|ImproperlyConfigured)(?::?).*)$', re.MULTILINE)
        exception_name_regex = re.compile(r'^(.*(?:Error|Exception|ImproperlyConfigured))(?::?.*)$', re.MULTILINE)
        # extract exception name alone
        buggy_errlines = re.findall(err_line_regex, repro_result.buggy_stdout)
        buggy_exceptions = re.findall(exception_regex, repro_result.buggy_stdout)
        buggy_exception_names = [
            exception_name_regex.match(exc).group(1).split(":")[0] for exc in buggy_exceptions
        ]
        buggy_exception_names = [
            exception_name.replace("+", "").replace("|", "").strip()
            for exception_name in buggy_exception_names
        ]
        if not buggy_errlines and repro_result.buggy_returncode != 0:
            buggy_errlines = ["NA"]
            buggy_exception_names = ["Timeout"]

        fixed_errlines = [] if repro_result.fixed_returncode == 0 else re.findall(err_line_regex, repro_result.fixed_stdout)
        fixed_exceptions = ""
        fixed_exception_names = []
        if fixed_errlines:
            fixed_exceptions = re.findall(exception_regex, repro_result.fixed_stdout)
            fixed_exception_names = [
                exception_name_regex.match(exc).group(1).split(":")[0] for exc in fixed_exceptions
            ]
            fixed_exception_names = [
                exception_name.replace("+", "").replace("|", "").strip()
                for exception_name in fixed_exception_names
            ]
        
        if not fixed_errlines and repro_result.fixed_returncode != 0:
            fixed_errlines = ["NA"]
            fixed_exception_names = ["Timeout"]
            
        
        # case 1: fixed passed
        if buggy_errlines:
            assert len(buggy_exception_names) > 0
            buggy_str = QuestionConstructor.ERROR_STR_TEMPLATE.format(
                lineno = buggy_errlines[-1],
                exception = buggy_exception_names[-1]
            )
        else:
            raise ValueError(f"No exceptions found in buggy output {repro_result.buggy_stdout}, buggy_returncode={repro_result.buggy_returncode}.")

        if not fixed_errlines:
            return {
                "after_patch_behavior": QuestionConstructor.PASSED_STR,
                "before_patch_behavior": buggy_str,
                "candidates": [QuestionConstructor.PASSED_STR, buggy_str]
            }
        else:
            if len(fixed_exception_names) == 0:
                fixed_exception_names = ["Exception"] # something did happen
            fixed_str = QuestionConstructor.ERROR_STR_TEMPLATE.format(
                lineno = fixed_errlines[-1],
                exception = fixed_exception_names[-1]
            )
            if buggy_errlines[-1] != fixed_errlines[-1]:
                more_candidates = [fixed_str, buggy_str]
            else:
                buggy_str = fixed_str
                more_candidates = [fixed_str]
            return {
                "after_patch_behavior": fixed_str,
                "before_patch_behavior": buggy_str,
                "candidates": [
                    QuestionConstructor.PASSED_STR
                ] + more_candidates
            }
    
    @staticmethod
    def question_expand(
        input_info: tuple
    ) -> dict:
        issue_description: str = input_info[0]
        pbt_source: str = input_info[1]
        existing_options: dict = input_info[2]
        numbered_pbt_source = "\n".join(
            f"{i+1}: {line}" for i, line in enumerate(pbt_source.splitlines())
        )
        user_prompt = (
            "Generate new possible outcomes of running a test case, "
            "given some information and existing possible outcomes.\n\n"
            f"Issue description: {issue_description}\n"
            f"Property-based test case:\n\n```python\n{numbered_pbt_source}\n````\n\n"
            f"Existing possible outcomes:\n"
            f"{json.dumps(existing_options, indent=2)}\n\n"
            "Generate 5 new possible outcomes that are different from the existing ones."
        )
        system_prompt = Path(SYSTEM_PROMPT).read_text()
        response = completion(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=ErrorInfoList,
            reasoning_effort="minimal"
        )
        content = response.choices[0].message.content
        assert content is not None
        response_info = ErrorInfoList.model_validate_json(content)
        for _ in range(3):
            new_candidates = [
                QuestionConstructor.ERROR_STR_TEMPLATE.format(
                    lineno = info.lineno,
                    exception = info.exception_type.split(":")[0]
                ) for info in response_info.info_list
            ]
            assert len(existing_options["candidates"]) == len(set(existing_options["candidates"])), "Existing candidates must be unique."
            if len(set(new_candidates) | set(existing_options["candidates"])) >= 4:
                strictly_old_candidates = existing_options["candidates"]
                strictly_new_candidates = list(set([
                    c for c in new_candidates if c not in strictly_old_candidates
                ]))
                choices = strictly_old_candidates + strictly_new_candidates
                choices = choices[:4] + ["The question cannot be answered based on the explanation alone."]
                assert existing_options["before_patch_behavior"] in choices and existing_options["after_patch_behavior"] in choices, f"Choices do not contain ground truth answers: {choices}, {q_info}"
                choices.sort()
                return {
                    "test_content": numbered_pbt_source,
                    "choices": choices,
                    "before_answer": "abcde"[choices.index(existing_options["before_patch_behavior"])],
                    "after_answer": "abcde"[choices.index(existing_options["after_patch_behavior"])],
                }
            else:
                print("Could not generate enough disjoint candidates, retrying...")
        raise ValueError("Could not generate enough disjoint candidates despite retries.")
    
    @staticmethod
    def generate_questions(
        exec_results: dict[str, FullReproResult],
        pbt_dict: dict[str, str],
        workers: int = 4
    ) -> tuple[dict[str, dict], dict[str, dict]]:
        questions: dict[str, dict] = {}
        context: dict[str, dict] = {}
        ground_truth: dict[str, dict] = {}
        for instance_id, repro_result in exec_results.items():
            try:
                seed = QuestionConstructor.question_seed(repro_result)
                if not seed:
                    print(instance_id)
                questions[instance_id] = seed
            except Exception as e:
                print(instance_id, type(e), e)
        instance_id_list = list(questions.keys())
        
        with Pool(workers) as pool:
            param_list = []
            for instance_id in instance_id_list:
                param_list.append((
                    _get_instance_by_suffix(instance_id)[0]["problem_statement"],
                    pbt_dict[instance_id],
                    questions[instance_id],
                ))
            for instance_id, aug_question_info in zip(
                instance_id_list,
                tqdm(pool.imap(
                    QuestionConstructor.question_expand,
                    param_list
                ), total = len(questions))
            ):
                questions[instance_id] = aug_question_info
                context[instance_id] = {k: v for k, v in aug_question_info.items() if k in ["test_content", "choices"]}
                ground_truth[instance_id] = {k: v for k, v in aug_question_info.items() if k in ["before_answer", "after_answer"]}
        sort_context = {k: context[k] for k in sorted(context.keys())}
        sort_gt = {k: ground_truth[k] for k in sorted(ground_truth.keys())}
        return sort_context, sort_gt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--swebench_pred_file", type=Path, required=True)
    parser.add_argument("--pbt_file", type=Path, required=True)
    parser.add_argument("--raw_file_output", type=Path)
    parser.add_argument("--output_dir", type=Path, default="./dataset/")
    parser.add_argument("--target_pattern", type=str, default="")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    swebench_pred_dict = read_swebench_pred_file(args.swebench_pred_file)
    agent_name = args.swebench_pred_file.name.removesuffix(".json")
    print(f"Read {len(swebench_pred_dict)} predictions from SweBench output.")
    pbt_dict = get_pbt_info(args.pbt_file)
    print(f"Read {len(pbt_dict)} PBT test cases.")
    target_dict = {
        k: v for k, v in pbt_dict.items() if args.target_pattern in k
    }

    if args.raw_file_output is None:
        result = run_pbts_on_patches(
            swebench_pred_dict,
            target_dict,
            workers = args.workers
        )

        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = args.output_dir / "raw_pbt_outputs.jsonl"
        with output_file.open("w") as f:
            for instance_id, repro_result in result.items():
                output_dict = {
                    "instance_id": instance_id,
                    "repro_status": f"{repro_result.failure_case!r}",
                    "buggy_stdout": repro_result.buggy_stdout,
                    "buggy_returncode": repro_result.buggy_returncode,
                    "fixed_stdout": repro_result.fixed_stdout,
                    "fixed_returncode": repro_result.fixed_returncode,
                }
                f.write(json.dumps(output_dict) + "\n")
    else:
        raw_content = args.raw_file_output.read_text()
        result = {
            d["instance_id"]: FullReproResult(
                buggy_stdout=d["buggy_stdout"],
                buggy_stderr="",
                buggy_returncode=d["buggy_returncode"],
                fixed_stdout=d["fixed_stdout"],
                fixed_stderr="",
                fixed_returncode=d["fixed_returncode"],
            ) for d in 
            [json.loads(l) for l in raw_content.splitlines()]
        }
        result = {
            k: v for k, v in result.items() if args.target_pattern in k
        }
    
    output_file = args.output_dir / "pbt_questions.jsonl"
    context, ground_truth = QuestionConstructor.generate_questions(
        result,
        target_dict,
        workers = args.workers
    )
    with open(args.output_dir / "context" / f"e2e_effect__{agent_name}.json", "w") as f:
        json.dump(context, f, indent=2)
    with open(args.output_dir / "ground_truths" / f"e2e_effect__{agent_name}.json", "w") as f:
        json.dump(ground_truth, f, indent=2)
    
