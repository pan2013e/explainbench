import json
import re
from pathlib import Path
import argparse

from test_execution.test_runner import setup
from test_execution.debugger.util import FunctionInfo
from test_execution.debugger.pdb_interface import PDBManager

def get_buggy_function_info(function_file: Path, instance_id: str) -> list[FunctionInfo]:
    bugloc_infos: list[dict] = [
        json.loads(line)
        for line in function_file.read_text().splitlines()
    ]
    target_bugloc_info = [
        info for info in bugloc_infos
        if info["instance_id"] == instance_id
    ]
    assert len(target_bugloc_info) == 1, f"Target bug locations non-singular: {target_bugloc_info}"

    buggy_methods = []
    for buggy_func_full_name in target_bugloc_info[0]["buggy_function_names"]:
        if "function:" not in buggy_func_full_name:
            continue # non-function locations ignored
        m = re.match(rf"{instance_id}/(.+)::(.*?)function:(.+?)(?:\.|$)", buggy_func_full_name)
        assert m is not None, f"Function name {buggy_func_full_name} could not be parsed!"
        file_name, func_scope_str, func_name = m.group(1), m.group(2), m.group(3)
        func_scopes = func_scope_str.removesuffix(".").removeprefix("class:")
        class_name = func_scopes.split("class:")[-1] if func_scopes else None
        buggy_methods.append(FunctionInfo(
            file=file_name,
            class_name=class_name,
            func_name=func_name
        ))
    return buggy_methods


def get_reproducer(reproducer_file: Path, instance_id: str) -> str:
    all_test_info = json.loads(reproducer_file.read_text())
    target_test_info = [t_info for t_info in all_test_info if t_info["instance_id"] == instance_id]
    return target_test_info[0]["test"]

def get_single_instance_io(
    instance_id: str, 
    reproducer_file: Path,
    function_file: Path,
    save_dir: Path,
    max_iter: int = 10, 
    debug: bool = False
) -> None:
    save_bug_dir = save_dir / instance_id
    save_bug_dir.mkdir(exist_ok = True)
    reproducer = get_reproducer(reproducer_file, instance_id)
    buggy_funcs = get_buggy_function_info(function_file, instance_id)

    container, bug_info = setup(instance_id)
    pdb_manager = PDBManager(container, bug_info, reproducer)
    for buggy_func in buggy_funcs:
        save_file = save_dir / (buggy_func.full_name + ".json")
        try:
            buggy_io = pdb_manager.get_func_io(buggy_func, max_iter = max_iter)
            fixed_io = pdb_manager.get_func_io(buggy_func, use_fixed=True, max_iter = max_iter)
        except Exception as e:
            print(f"Oh no, exception for {instance_id} - {type(e)}: {e}")
            continue
        save_file.write_text(json.dumps({
            "buggy_io": [info.to_dict() for info in buggy_io],
            "fixed_io": [info.to_dict() for info in fixed_io],
        }, indent=2))
    
    if not debug:
        pdb_manager.exit()

def main(args):
    with open(args.test_file) as f:
        all_test_info = json.load(f)
    
    instance_list = [e["instance_id"] for e in all_test_info]
    if args.target_pattern != "":
        instance_list = [
            e for e in instance_list if args.target_pattern in e
        ]
    
    for instance_id in instance_list:
        get_single_instance_io(
            instance_id,
            args.reproducer_file,
            args.buggy_function_file,
            args.save_dir,
            args.max_iter,
            args.debug
        )    


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--reproducer_file", type=str)
    parser.add_argument("--save_dir", type=str)
    parser.add_argument("--buggy_function_file", type=str, default="./dataset/extract_ground_truths/localization/ground_truth_w_fullname.jsonl")
    parser.add_argument("--target_pattern", type=str, default="")
    parser.add_argument("--max_iter", type=int, default=10)
    parser.add_argument("--debug", action='store_true')
    args = parser.parse_args()

    main(args)