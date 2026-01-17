#!/usr/bin/env python3
import argparse
import json
from typing import Dict, Iterable, Tuple, Any


def iter_instances(data: Any, agent: str | None = None) -> Iterable[Tuple[str, Dict[str, Any]]]:
    if isinstance(data, dict):
        if agent is not None and agent in data and isinstance(data[agent], dict):
            for instance_id, payload in data[agent].items():
                if isinstance(payload, dict):
                    yield instance_id, payload
            return
        if len(data) == 1:
            only_value = next(iter(data.values()))
            if isinstance(only_value, dict):
                for instance_id, payload in only_value.items():
                    if isinstance(payload, dict):
                        yield instance_id, payload
                return
        for instance_id, payload in data.items():
            if isinstance(payload, dict):
                yield instance_id, payload
    elif isinstance(data, list):
        for payload in data:
            if isinstance(payload, dict) and "instance_id" in payload:
                yield payload["instance_id"], payload


def should_exclude(payload: Dict[str, Any]) -> bool:
    buggy = payload.get("raw_to_filtered_buggy_distance")
    patched = payload.get("raw_to_filtered_patched_distance")
    return (buggy is not None and buggy > 0) or (patched is not None and patched > 0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print instance IDs where raw_to_filtered_buggy_distance or "
            "raw_to_filtered_patched_distance is > 0."
        )
    )
    parser.add_argument("--json_path", help="Path to the JSON file to inspect.", default="/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step/step1.with-depth.json")
    parser.add_argument(
        "--agent",
        default=None,
        help="Optional top-level agent key (e.g., gold).",
    )
    args = parser.parse_args()

    with open(args.json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for instance_id, payload in iter_instances(data, agent=args.agent):
        if should_exclude(payload):
            print(instance_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
