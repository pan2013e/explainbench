import glob
import os
import re
import json
from pathlib import Path
import argparse

from test_execution.debugger.util import IOInfo

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
            raise ValueError(f'Different output for same input: unresolvable bug')
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

def main(args):
    all_jsons = get_io_files(Path(args.io_info_dir))
    save_json = Path(args.save_path)
    bug2question_info = dict()
    max_q = args.question_num
    for json_file in all_jsons:
        buggy_ios, fixed_ios = read_io_file(json_file)
        if len(fixed_ios) == 0:
            continue

        try:
            io_pairs, max_score = rank_fixed_io(fixed_ios, buggy_ios)
        except ValueError:
            continue
        
        instance_id = json_file.parent.name
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
    
    print('Successes:', len(bug2question_info))
    save_values = list(bug2question_info.values())
    save_values = list(sorted(save_values, key=lambda d: d['instance_id']))
    save_json.write_text(json.dumps(save_values, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--io_info_dir", type=str)
    parser.add_argument("--save_path", type=str)
    parser.add_argument("--question_num", type=int, default=3)
    args = parser.parse_args()

    main(args)