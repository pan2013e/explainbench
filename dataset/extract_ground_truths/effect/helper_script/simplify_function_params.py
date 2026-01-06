#!/usr/bin/env python3
import argparse
import json
from typing import Any, Dict, List


def _type_stub(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        keys = [x for x in value.keys() if not x.startswith("py/")]
        if "py/object" in value and keys:
            return {"__type__": value["py/object"], "__available_attributes__": keys}
        if "py/type" in value and keys:
            return {"__type__": value["py/type"], "__available_attributes__": keys}
        return {"__type__": "dict"}
    if isinstance(value, list):
        return {"__type__": "list", "len": len(value)}
    return {"__type__": type(value).__name__}


def _simplify(value: Any, max_depth: int, depth: int) -> Any:
    # Depth counts nested levels below the outermost container.
    if isinstance(value, dict):
        if depth > max_depth:
            return _type_stub(value)
        return {k: _simplify(v, max_depth, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if depth > max_depth:
            return _type_stub(value)
        return [_simplify(v, max_depth, depth + 1) for v in value]
    return value


def simplify_params(data: Dict[str, Dict[str, Dict[str, Any]]], max_depth: int) -> None:
    for agent_data in data.values():
        for metadata in agent_data.values():
            if metadata:
                for key in (
                    "buggy_function_param",
                    "patched_function_param",
                    "buggy_variables",
                    "patched_variables",
                ):
                    if key in metadata:
                        metadata[key] = _simplify(metadata[key], max_depth, depth=0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Simplify nested function param dicts by truncating beyond a max depth."
        )
    )
    parser.add_argument("--input_json", help="Path to the input JSON file.", default="/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-3/step1.gold.depth-filtered-3.json")
    parser.add_argument("--output_json", help="Path to write the simplified JSON.", default="/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-3/step1.gold.depth-filtered-3.simplified.json")
    parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        help="Maximum nested depth excluding the outermost container (default: 3).",
    )
    args = parser.parse_args()

    with open(args.input_json, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    simplify_params(data, args.max_depth)

    with open(args.output_json, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True, indent=2)


if __name__ == "__main__":
    main()
