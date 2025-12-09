import glob
import os
import re
import json
from pathlib import Path
import argparse

from test_execution.debugger.util import IOInfo

GT_FL_FILE = "./dataset/extract_ground_truths/localization/ground_truth_w_fullname.jsonl"

## Processing IO files and their contents

def get_io_files(root_dir: Path) -> list[Path]:
    json_files = glob.glob('**/*.json', recursive=True, root_dir=root_dir)
    json_paths = [Path(os.path.join(root_dir, json_file)) for json_file in json_files]
    return json_paths

def read_io_file(json_path: Path) -> tuple[list[IOInfo], list[IOInfo]]:
    io_info = json.loads(json_path.read_text())
    buggy_ios = [IOInfo.from_dict(io_dict) for io_dict in io_info['buggy_io']]
    fixed_ios = [IOInfo.from_dict(io_dict) for io_dict in io_info['fixed_io']]
    return buggy_ios, fixed_ios

## Processing IOInfo objects

def redact_addrs(value_str: str) -> str:
    return re.sub('at 0x[0-9a-fA-F]+', 'at [addr]', value_str)

def ioinfo_to_strings(io_info: IOInfo) -> tuple[str, str]:
    input_str, output_str = redact_addrs(io_info.input_values), io_info.output_value
    return input_str, output_str

## Scoring and ranking

def score_io(buggy_ios: dict[str, str], seen_fixed_ios: dict[str, str], io_info: IOInfo) -> int:
    input_str, output_str = ioinfo_to_strings(io_info)
    if input_str in seen_fixed_ios:
        if output_str != seen_fixed_ios[input_str]:
            raise ValueError(f'Different output for same input :{input_str}: unresolvable bug')
        score = -1
    elif output_str in seen_fixed_ios.values():
        score = 0
    else:
        score = 1
    if input_str in buggy_ios and buggy_ios[input_str] == output_str:
        score -= 2
    return score

def rank_fixed_io(fixed_ios: list[IOInfo], buggy_ios: list[IOInfo]) -> tuple[list[tuple[str, str]], int]:
    buggy_io_dict: dict[str, str] = {
        redact_addrs(io_info.input_values): io_info.output_value 
        for io_info in buggy_ios
    }
    seen_fixed_ios: dict[str, str] = dict()
    scores: list[int] = []

    for io_info in fixed_ios:
        score = score_io(buggy_io_dict, seen_fixed_ios, io_info)
        input_str, output_str = ioinfo_to_strings(io_info)
        seen_fixed_ios[input_str] = output_str
        scores.append(score)
    
    assert len(scores) == len(fixed_ios)
    assert 0 < len(seen_fixed_ios) <= len(fixed_ios)

    ranked_ios = sorted(zip(fixed_ios, scores), key=lambda x: x[1], reverse=True)
    ranked_io_strs = [
        ioinfo_to_strings(io_pair)
        for io_pair, score in ranked_ios
        if score >= 0
    ]
    return (ranked_io_strs, max(scores))

def _analyze_results(
    all_jsons: list[Path], 
    bug2question_info: dict[str, dict],
    all_bugs: set[str],
    all_with_methods: set[str]
) -> dict:
    from collections import Counter
    io_attempted_instance_ids = set()
    for json_file in all_jsons:
        instance_id = json_file.parent.name
        io_attempted_instance_ids.add(instance_id)
    
    io_gathered_instance_ids = set(bug2question_info.keys())
    io_failed_instance_ids = io_attempted_instance_ids - io_gathered_instance_ids
    
    attempted_by_project = Counter(
        [instance_id.split("-")[0] for instance_id in io_attempted_instance_ids]
    )
    failed_by_project = Counter(
        [instance_id.split("-")[0] for instance_id in io_failed_instance_ids]
    )
    result_dict = dict()
    result_dict["pbt_exists"] = len(all_bugs)
    result_dict["pbt_exists_and_buggy_method"] = len(all_bugs & all_with_methods)
    result_dict["io_gathered"] = len(io_attempted_instance_ids)
    result_dict["failure"] = len(io_failed_instance_ids)
    for repo_name in attempted_by_project:
        total = len([e for e in (all_bugs & all_with_methods) if repo_name in e])
        result_dict[repo_name] = {
            "total": total,
            "io_gathered": attempted_by_project[repo_name],
            "io_ungathered": total - attempted_by_project[repo_name],
            "io_uninformative": failed_by_project[repo_name],
            "ratio": failed_by_project[repo_name] / total,
        }
    return result_dict


def get_all_bugs_with_methods() -> set[str]:
    fl_results = Path(GT_FL_FILE).read_text()
    has_method_bugs = set()
    for line in fl_results.splitlines():
        line_obj = json.loads(line)
        if any(["function:" in name for name in line_obj["buggy_function_names"]]):
            has_method_bugs.add(line_obj["instance_id"])
    return has_method_bugs


def main(args):
    all_bugs_with_pbts = set(os.listdir(args.io_info_dir))
    all_bugs_with_buggy_methods = get_all_bugs_with_methods()
    all_jsons = get_io_files(Path(args.io_info_dir))
    save_json = Path(args.save_path)
    bug2question_info = dict()
    max_q = args.question_num
    for json_file in all_jsons:
        instance_id = json_file.parent.name
        buggy_ios, fixed_ios = read_io_file(json_file)
        if len(fixed_ios) == 0:
            continue

        try:
            io_pairs, max_score = rank_fixed_io(fixed_ios, buggy_ios)
        except ValueError:
            continue
        
        method_has_better_score = (
            (instance_id not in bug2question_info) or
            (max_score > bug2question_info[instance_id]['max_score'])
        )
        if method_has_better_score:
            bug2question_info[instance_id] = {
                'instance_id': instance_id, 
                'signature': json_file.name.removesuffix('.json'), 
                'example_inputs': [pair[0] for pair in io_pairs][:max_q], 
                'answers': [pair[1] for pair in io_pairs][:max_q],
                'max_score': max_score
            }
    
    save_values = list(bug2question_info.values())
    save_values = list(sorted(save_values, key=lambda d: d['instance_id']))
    save_json.write_text(json.dumps(save_values, indent=2))

    if args.display_result_analysis:
        analyzed_results = _analyze_results(
            all_jsons, bug2question_info,
            all_bugs_with_pbts, all_bugs_with_buggy_methods
        )
        print(json.dumps(analyzed_results, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--io_info_dir", type=str)
    parser.add_argument("--save_path", type=str)
    parser.add_argument("--question_num", type=int, default=3)
    parser.add_argument("--display_result_analysis", action="store_true")
    args = parser.parse_args()

    main(args)