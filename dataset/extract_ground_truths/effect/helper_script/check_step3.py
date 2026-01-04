#!/usr/bin/env python3
"""Summarize per-agent metadata validity in step3.json."""

from __future__ import annotations

import argparse
import json
from typing import Any


def is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, tuple, set, dict)):
        return len(value) > 0
    return bool(value)


def summarize(
    path: str,
) -> tuple[list[tuple[str, int, int, int, int, int]], set[str]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    valid_both_sets: dict[str, set[str]] = {}
    for agent, instances in data.items():
        total = 0
        valid_both = 0
        only_changed_empty = 0
        only_unchanged_empty = 0
        both_empty = 0
        reachability = 0
        valid_both_instances: set[str] = set()
        for _instance_id, meta in instances.items():
            total += 1
            if meta.get("choices"):
                reachability += 1
                valid_both_instances.add(_instance_id)
                continue
            changed_ok = is_nonempty(meta.get("valid_changed_expressions"))
            unchanged_ok = is_nonempty(meta.get("valid_unchanged_expressions"))
            if changed_ok and unchanged_ok:
                valid_both += 1
                valid_both_instances.add(_instance_id)
            elif (not changed_ok) and unchanged_ok:
                only_changed_empty += 1
            elif changed_ok and (not unchanged_ok):
                only_unchanged_empty += 1
            else:
                print(agent, _instance_id)
                both_empty += 1
        valid_both_sets[agent] = valid_both_instances
        rows.append(
            (
                agent,
                total,
                reachability,
                valid_both,
                only_changed_empty,
                only_unchanged_empty,
                both_empty,
            )
        )

    rows.sort(key=lambda r: r[0])
    intersection: set[str]
    if valid_both_sets:
        intersection = set.intersection(*valid_both_sets.values())
    else:
        intersection = set()
    return rows, intersection


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check per-agent metadata validity for step3.json"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-3/step3.json",
        help="Path to step3.json",
    )
    args = parser.parse_args()

    rows, intersection = summarize(args.path)
    header = (
        "agent",
        "total_instances",
        "reachability",
        "valid_both_nonempty",
        "only_changed_empty",
        "only_unchanged_empty",
        "both_empty",
    )
    widths = [len(h) for h in header]
    for row in rows:
        widths = [max(w, len(str(v))) for w, v in zip(widths, row)]

    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*header))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*row))
    print()
    print("valid_both_nonempty_intersection", len(intersection))


if __name__ == "__main__":
    main()