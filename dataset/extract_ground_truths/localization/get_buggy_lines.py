import json
from pathlib import Path
from bisect import bisect_right
from typing import List, Dict, Any


RELEVANT_ACTIONS = ['delete-node', 'delete-tree', 'move-tree', 'update-node']

def char_offsets_to_line_numbers(file_path: str)->List[int]:
    "Create a list of the starting character offsets for each line in a file."
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    cum_offsets = [0]
    for line in lines:
        cum_offsets.append(cum_offsets[-1] + len(line))
    return cum_offsets


def offset_to_line(offset, cum_offsets):
    "Find the line number corresponding to a given character offset."
    return bisect_right(cum_offsets, offset)


def get_buggy_lines_from_gumtree(gumtree_path: str, before_file_path: str) -> List[int]:
    "Read a GumTree JSON output file, extract all the code changes, and return a sorted list of unique line numbers in the original file that were affected by those changes."
    with open(gumtree_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cum_offsets = char_offsets_to_line_numbers(before_file_path)

    buggy_lines = set()
    actions = data.get('actions', [])
    actions = [x for x in actions if x.get("action") in RELEVANT_ACTIONS]
    for change in actions:
        tree_str = change.get('tree', '')
        if '[' in tree_str and ']' in tree_str:
            # Extract the start and end character offsets
            start_char, end_char = tree_str.split('[')[1].split(']')[0].split(',')
            start_char = int(start_char)
            end_char = int(end_char)

            start_line = offset_to_line(start_char, cum_offsets)
            end_line = offset_to_line(end_char, cum_offsets)

            buggy_lines.update(range(start_line, end_line + 1))

    return sorted(buggy_lines)

def get_buggy_lines(record: Dict[str, Any], dataset_dir: str)->Dict[str, Any]:
    """
    Get the lines from a gumtree diff
    """
    gumtree_files = record.get("gumtree_files", [])
    output = set()
    for gumtree_path in gumtree_files:
        path = Path(dataset_dir, gumtree_path)
        basename = path.stem
        parent_dir = path.parent
        old_path = Path(parent_dir, f"old_{basename}.py")

        buggy_lines = get_buggy_lines_from_gumtree(str(path), str(old_path))

        output.add((f"{basename}.py", tuple(buggy_lines)))
    record["buggy_lines_by_file"] = sorted(list(output))
    return record



# if __name__ == "__main__":
#     gumtree_path = "/home/yusuf/explainbench/dataset/extract_ground_truths/localization/swe_bench_files/django__django-10973/django/db/backends/postgresql/client.json"
#     before_file_path = "/home/yusuf/explainbench/dataset/extract_ground_truths/localization/swe_bench_files/django__django-10973/django/db/backends/postgresql/old_client.py"
#     buggy_lines = get_buggy_lines_from_gumtree(gumtree_path, before_file_path)
#     print(buggy_lines)