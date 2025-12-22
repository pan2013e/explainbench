import json
import re
from pathlib import Path
import argparse
from multiprocessing import Pool

from tqdm import tqdm

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
    if len(target_bugloc_info) == 0:
        return []
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
    assert reproducer_file.name.endswith(".jsonl")
    all_test_info = list(map(json.loads, reproducer_file.read_text().splitlines()))
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
    save_bug_dir.mkdir(exist_ok = True, parents = True)
    reproducer = get_reproducer(reproducer_file, instance_id)
    buggy_funcs = get_buggy_function_info(function_file, instance_id)
    if not buggy_funcs:
        return

    container, bug_info = setup(instance_id)
    pdb_manager = PDBManager(container, bug_info, reproducer)
    for buggy_func in buggy_funcs:
        save_file = save_bug_dir / (buggy_func.full_name + ".json")
        try:
            buggy_io, bug_error_str = pdb_manager.get_func_io(buggy_func, max_iter = max_iter)
            fixed_io, fix_error_str = pdb_manager.get_func_io(buggy_func, use_fixed=True, max_iter = max_iter)
        except Exception as e:
            print(f"Oh no, exception for {instance_id} - {type(e)}: {e}")
            continue

        if (bug_error_str and fix_error_str):
            error_file = save_file.parent / f"error.{buggy_func.full_name}.txt"
            error_file.write_text(bug_error_str)
        else:
            save_file.write_text(json.dumps({
                "buggy_io": [info.to_dict() for info in buggy_io],
                "fixed_io": [info.to_dict() for info in fixed_io],
            }, indent=2))
    
    if not debug:
        pdb_manager.exit()

def get_single_instance_wrapper(args):
    get_single_instance_io(*args)

def main(args):
    all_test_info = []
    with open(args.reproducer_file) as f:
        for line in f:
            all_test_info.append(json.loads(line))
    
    instance_list = [e["instance_id"] for e in all_test_info]
    if args.target_pattern != "":
        instance_list = [
            e for e in instance_list if args.target_pattern in e
        ]
    
    param_list = []
    for instance_id in instance_list:
        param_list.append((
            instance_id,
            Path(args.reproducer_file),
            Path(args.buggy_function_file),
            Path(args.save_dir),
            args.max_iter,
            args.debug
        ))
    
    with Pool(args.workers) as pool:
        for _ in tqdm(pool.imap_unordered(get_single_instance_wrapper, param_list),
                      total=len(param_list)):
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--reproducer_file", type=str)
    parser.add_argument("--save_dir", type=str)
    parser.add_argument("--buggy_function_file", type=str, default="./dataset/extract_ground_truths/localization/ground_truth_w_fullname.jsonl")
    parser.add_argument("--target_pattern", type=str, default="")
    parser.add_argument("--max_iter", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--debug", action='store_true')
    args = parser.parse_args()

    main(args)