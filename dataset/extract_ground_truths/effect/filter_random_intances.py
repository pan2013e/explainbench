# Implementation from the previous step + runnable, concrete examples

import argparse
import json
from typing import Any, List, Dict, Iterable, TextIO
from pathlib import Path
import sys

_REMOVE = object()

def prune_equal_leaves(a: Any, b: Any) -> Any:
    """
    Return a new structure from `a` that keeps only leaves equal to the
    corresponding leaves in `b`. Containers (dict/list/tuple) are preserved
    structurally and may become empty. Assumes:
      - dict keys match at each level
      - corresponding types match
      - corresponding list/tuple lengths match
    """
    def _prune(x: Any, y: Any):
        # Leaves: anything that's not dict/list/tuple
        if not isinstance(x, (dict, list, tuple)):
            return x if x == y else _REMOVE

        if type(x) is not type(y):
            raise TypeError(f"Type mismatch: {type(x).__name__} vs {type(y).__name__}")

        if isinstance(x, dict):
            if x.keys() != y.keys():
                missing_in_y = x.keys() - y.keys()
                missing_in_x = y.keys() - x.keys()
                raise KeyError(f"Dict keys differ. Missing_in_y={missing_in_y}, Missing_in_x={missing_in_x}")
            out = {}
            for k in x:
                child = _prune(x[k], y[k])
                if child is not _REMOVE:
                    out[k] = child
            return out

        if isinstance(x, list):
            if len(x) != len(y):
                raise ValueError(f"List length mismatch: {len(x)} vs {len(y)}")
            out = []
            for i in range(len(x)):
                child = _prune(x[i], y[i])
                if child is not _REMOVE:
                    out.append(child)
            return out

        if isinstance(x, tuple):
            if len(x) != len(y):
                raise ValueError(f"Tuple length mismatch: {len(x)} vs {len(y)}")
            out_items = []
            for i in range(len(x)):
                child = _prune(x[i], y[i])
                if child is not _REMOVE:
                    out_items.append(child)
            return tuple(out_items)

        raise TypeError(f"Unsupported container type: {type(x).__name__}")

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
            pruned.append(prune_equal_leaves(a, b))
        except Exception as e:
            raise RuntimeError(f"Error pruning record at index {idx} (line {idx+1}): {e}") from e

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(pruned, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))