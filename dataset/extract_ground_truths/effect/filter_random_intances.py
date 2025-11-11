# Implementation from the previous step + runnable, concrete examples

import argparse
import json
from typing import Any, List, Dict, Iterable, TextIO
from pathlib import Path
import sys

_REMOVE = object()

def filter_dict_keys_like(A: Any, B: Any, *, strict: bool = True, _path: str = "") -> Any:
    """
    Recursively build a NEW object from A that keeps only dictionary entries
    whose keys ALSO exist in the corresponding dictionary in B.

    Assumptions:
      - A and B have the same overall structure (same container types, same list/tuple lengths).
      - Only dict keys may differ.

    Rules:
      - dict vs dict: keep k: A[k] only if k in B; recurse on values.
      - list/tuple vs list/tuple: recurse positionally on each element.
      - all other types: return A unchanged.
    """
    # Dict case
    if isinstance(A, dict):
        if strict and not isinstance(B, dict):
            raise TypeError(f"Structure mismatch at {_path or '<root>'}: A is dict, B is {type(B).__name__}")
        if not isinstance(B, dict):
            return {}

        out = {}
        # intersection is sufficient since we only keep keys present in B
        for k in A.keys() & B.keys():  
            next_path = f"{_path}.{k}" if _path else str(k)
            out[k] = filter_dict_keys_like(A[k], B[k], strict=strict, _path=next_path)
        return out

    # List case
    if isinstance(A, list):
        if strict and not isinstance(B, list):
            raise TypeError(f"Structure mismatch at {_path or '<root>'}: A is list, B is {type(B).__name__}")
        if not isinstance(B, list):
            return list(A)
        if strict and len(A) != len(B):
            raise ValueError(f"Length mismatch at {_path or '<root>'}: len(A)={len(A)} != len(B)={len(B)}")
        n = min(len(A), len(B))
        return [filter_dict_keys_like(A[i], B[i], strict=strict, _path=f"{_path}[{i}]") for i in range(n)] + (A[n:] if len(A) > n else [])

    # Tuple case
    if isinstance(A, tuple):
        if strict and not isinstance(B, tuple):
            raise TypeError(f"Structure mismatch at {_path or '<root>'}: A is tuple, B is {type(B).__name__}")
        if not isinstance(B, tuple):
            return tuple(A)
        if strict and len(A) != len(B):
            raise ValueError(f"Length mismatch at {_path or '<root>'}: len(A)={len(A)} != len(B)={len(B)}")
        n = min(len(A), len(B))
        filtered = tuple(filter_dict_keys_like(A[i], B[i], strict=strict, _path=f"{_path}[{i}]") for i in range(n))
        if len(A) > n:
            filtered += tuple(A[n:])
        return filtered
    return A

def prune_equal_leaves(a: Any, b: Any, *, strict: bool = False) -> Any:
    """
    Return a new structure from `a` that keeps only leaves equal to the
    corresponding leaves in `b`. Containers (dict/list/tuple) are preserved
    structurally and may become empty.

    Behavior (default, permissive):
      - Dicts: traverse intersection of keys (x.keys() & y.keys()).
      - Lists/Tuples: traverse positionally up to min(len(x), len(y)).
      - Leaves: keep x if x == y, else drop.
      - Containers may become empty.

    If strict=True:
      - Dicts: keys must match exactly, else raise KeyError.
      - Lists/Tuples: lengths must match exactly, else raise ValueError.
      - Types of corresponding containers must match, else raise TypeError.
    """
    def _prune(x: Any, y: Any):
        # Leaves: anything that's not dict/list/tuple
        if not isinstance(x, (dict, list, tuple)):
            return x if x == y else _REMOVE

        # Container type check (only when both are containers)
        if not isinstance(y, (dict, list, tuple)):
            # x is container but y is not: no equal leaves possible under x
            return _REMOVE

        if type(x) is not type(y):
            if strict:
                raise TypeError(f"Type mismatch: {type(x).__name__} vs {type(y).__name__}")
            # Permissive: no structural overlap to compare
            return _REMOVE

        if isinstance(x, dict):
            if strict and x.keys() != y.keys():
                missing_in_y = x.keys() - y.keys()
                missing_in_x = y.keys() - x.keys()
                raise KeyError(f"Dict keys differ. Missing_in_y={missing_in_y}, Missing_in_x={missing_in_x}")
            keys = (x.keys() & y.keys()) if not strict else x.keys()
            out = {}
            for k in keys:
                child = _prune(x[k], y[k])
                if child is not _REMOVE:
                    out[k] = child
            return out

        if isinstance(x, list):
            if strict and len(x) != len(y):
                raise ValueError(f"List length mismatch: {len(x)} vs {len(y)}")
            n = min(len(x), len(y)) if not strict else len(x)
            out = []
            for i in range(n):
                child = _prune(x[i], y[i])
                if child is not _REMOVE:
                    out.append(child)
            return out

        if isinstance(x, tuple):
            if strict and len(x) != len(y):
                raise ValueError(f"Tuple length mismatch: {len(x)} vs {len(y)}")
            n = min(len(x), len(y)) if not strict else len(x)
            out_items = []
            for i in range(n):
                child = _prune(x[i], y[i])
                if child is not _REMOVE:
                    out_items.append(child)
            return tuple(out_items)

        return _REMOVE

    return _prune(a, b)

def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load a JSON Lines file into a list of dicts."""
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for ln, line in enumerate(f, start=1):
            line = line.strip()
            obj = json.loads(line)
            records.append(obj)
    return records

def write_jsonl(records: Iterable[Dict[str, Any]], path: Path) -> None:
    """Write records as JSON Lines."""
    with path.open("w", encoding="utf-8") as f:
        for obj in records:
            f.write(json.dumps(obj, ensure_ascii=False))
            f.write("\n")


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Prune differing leaves from JSONL A using JSONL B (matching structure/types/lengths)."
    )
    p.add_argument("--input1", required=True, type=Path, help="Path to input JSONL A (one dict per line).")
    p.add_argument("--input2", required=True, type=Path, help="Path to input JSONL B (one dict per line).")
    p.add_argument("--out", required=True, type=Path, help="Output path (.json or .jsonl).")
    return p.parse_args(argv)


def infer_format(out_path: Path, explicit: str | None) -> str:
    if explicit in {"json", "jsonl"}:
        return explicit
    ext = out_path.suffix.lower()
    if ext == ".jsonl":
        return "jsonl"
    if ext == ".json":
        return "json"
    # default
    return "json"


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    a_list = load_jsonl(args.input1)
    b_list = load_jsonl(args.input2)

    if len(a_list) != len(b_list):
        raise ValueError(f"Input JSONL files must have the same number of lines: "
                         f"{args.input1} has {len(a_list)}, {args.input2} has {len(b_list)}")
    pruned: List[Dict[str, Any]] = []
    for idx, (a, b) in enumerate(zip(a_list, b_list)):
            try:
                if "seen_variables" in a and a["seen_variables"] != b["seen_variables"]:
                    new_seen_variables = {}
                    new_seen_variables = filter_dict_keys_like(a["seen_variables"], b["seen_variables"])
                    new_seen_variables = prune_equal_leaves(new_seen_variables, b["seen_variables"]) if new_seen_variables else {}
                    a["seen_variables"] = new_seen_variables
                pruned.append(a)
            except Exception as e:
                raise RuntimeError(f"Error pruning record at index {idx} (line {idx+1}): {e}") from e

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(pruned, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))