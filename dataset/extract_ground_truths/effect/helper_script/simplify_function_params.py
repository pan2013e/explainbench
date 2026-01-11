#!/usr/bin/env python3
import argparse
import json

from dataset.extract_ground_truths.effect.build_step1 import simplify_params

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
        default=4,
        help="Maximum nested depth excluding the outermost container (default: 4).",
    )
    args = parser.parse_args()

    with open(args.input_json, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    simplify_params(data, args.max_depth)

    with open(args.output_json, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True, indent=2)


if __name__ == "__main__":
    main()
