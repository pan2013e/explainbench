import re
from collections import defaultdict
from typing import Dict, List
from pathlib import Path

def extract_modified_lines(patch_content: str)->Dict[str, Dict]:
    """
    Parses a patch file content and extracts metadata about the changes.
    """
    # File headers: a/<path>\n+++ b/<path>\n  (a/ and b/ optional)
    file_header_pattern = re.compile(r'--- (?:a/)?(.*?)\n\+\+\+ (?:b/)?(.*?)\n')

    # Hunk headers: @@ -<old_start>[,<old_count>] +<new_start>[,<new_count>] @@<context>\n
    hunk_header_pattern = re.compile(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*?)\n')

    added: Dict[str, List[int]] = defaultdict(list)
    removed: Dict[str, List[int]] = defaultdict(list)

    file_patches = patch_content.split('diff --git ')[1:]
    for file_patch in file_patches:
        file_header_match = file_header_pattern.search(file_patch)
        if not file_header_match:
            continue

        old_path = file_header_match.group(1)
        new_path = file_header_match.group(2)

        hunks_iter = list(hunk_header_pattern.finditer(file_patch))
        split_parts = hunk_header_pattern.split(file_patch)[1:]

        # pattern has 3 capturing groups; for match i, the body sits at index (i*4)+3
        for i, h in enumerate(hunks_iter):
            removal_start = int(h.group(1))
            addition_start = int(h.group(2))

            hunk_body_index = (i * 4) + 3
            if hunk_body_index >= len(split_parts):
                continue
            hunk_body = split_parts[hunk_body_index]

            old_line_num = removal_start
            new_line_num = addition_start
            removal_line_numbers: List[int] = []
            addition_line_numbers: List[int] = []

            for line in hunk_body.split('\n'):
                if not line:
                    continue
                if line.startswith('-'):   
                    removal_line_numbers.append(old_line_num)
                    old_line_num += 1
                elif line.startswith('+'): 
                    addition_line_numbers.append(new_line_num)
                    new_line_num += 1
                elif line.startswith(' '): 
                    old_line_num += 1
                    new_line_num += 1
                else:
                    pass

            if addition_line_numbers:
                added[new_path].extend(addition_line_numbers)
            if removal_line_numbers:
                removed[old_path].extend(removal_line_numbers)

    added_sorted = {path: sorted(set(nums)) for path, nums in added.items() if nums}
    removed_sorted = {path: sorted(set(nums)) for path, nums in removed.items() if nums}

    return {
        "added": added_sorted,
        "removed": removed_sorted,
    }

def read_patch(input_filepath: Path)->str:
    with open(input_filepath, "r") as f:
        return f.read()

def get_diff_info_per_instance(agent_output_dir: Path, instance_id: Path)->Dict[str, Dict]:
    patch_path = Path(agent_output_dir, instance_id, "patch.diff")
    try:
        patch_content = read_patch(patch_path)
        modified_lines = extract_modified_lines(patch_content)
        return modified_lines
    except FileNotFoundError:
        print(f"{patch_path} does not exists")
    return {}

def get_all_instance_ids(agent_output_dir: Path)->List[Path]:
    outputs= []
    for dir in agent_output_dir.iterdir():
        if dir.is_dir():
            outputs.append(Path(agent_output_dir, dir))
    return outputs

def get_diff_info_per_agent(output_dir: str, run_id: str, agent_id: str)->Dict:
    agent_output_dir = Path(output_dir, run_id, agent_id)
    instance_ids = get_all_instance_ids(agent_output_dir)
    records = {}
    for id in instance_ids:
        records[id] = {}
        record = get_diff_info_per_instance(
            agent_output_dir,
            id
        )
        if record:
            records[id] = record

    return records

if __name__ == "__main__":
    diff_info = get_diff_info_per_instance(
        agent_output_dir=Path("/home/yusuf/explainbench/logs/run_evaluation/validate-gold/gold"),
        instance_id=Path("astropy__astropy-13033")
    )

    expected = {
        "added": {
            "astropy/timeseries/core.py": [58, 59, 60, 61, 62, 63, 64, 86, 87, 88, 89]
        },
        "removed": {
            "astropy/timeseries/core.py": [79, 80, 81]
        }
    }
    assert diff_info == expected


    diff_info_per_agent = get_diff_info_per_agent(
        "/home/yusuf/explainbench/logs/run_evaluation",
        "validate-gold",
        "gold"
    )

    for key in diff_info_per_agent:
        print(diff_info_per_agent[key])
        print("---"*50)