#!/usr/bin/env python

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, Set, Tuple, Any


def load_step3(path: Path) -> Dict[str, Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def filter_instances(
    data: Dict[str, Dict[str, Any]],
    n_valid: int,
    n_invalid: int,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, int], Dict[str, int]]:
    """
    Filter instances per agent based on the number of valid expressions.

    Keeps only instances where:
      - len(valid_changed_expressions)  >= n_valid
      - len(valid_unchanged_expressions) >= n_invalid

    Returns:
      filtered_data: same structure as input but pruned
      removed_counts: per-agent number of removed instances
      total_counts: per-agent total instances before filtering
    """
    filtered: Dict[str, Dict[str, Any]] = {}
    removed_counts: Dict[str, int] = {}
    total_counts: Dict[str, int] = {}

    for agent, instances in data.items():
        if not isinstance(instances, dict):
            continue

        kept_for_agent: Dict[str, Any] = {}
        removed = 0
        total = 0

        for instance_id, metadata in instances.items():
            total += 1

            if not isinstance(metadata, dict):
                removed += 1
                continue

            valid_changed = metadata.get("valid_changed_expressions") or []
            valid_unchanged = metadata.get("valid_unchanged_expressions") or []

            if (len(valid_changed) >= n_valid and len(valid_unchanged) >= n_invalid) or "choices" in metadata:
                kept_for_agent[instance_id] = metadata
            else:
                removed += 1

        if kept_for_agent:
            filtered[agent] = kept_for_agent

        removed_counts[agent] = removed
        total_counts[agent] = total

    return filtered, removed_counts, total_counts


def agent_to_ids(data: Dict[str, Dict[str, Any]]) -> Dict[str, Set[str]]:
    mapping: Dict[str, Set[str]] = {}
    for agent, instances in data.items():
        if isinstance(instances, dict):
            mapping[agent] = set(instances.keys())
    return mapping


def pairwise_intersections(agent_to_ids_map: Dict[str, Set[str]]) -> Iterable[str]:
    agents = sorted(agent_to_ids_map.keys())
    for i, a in enumerate(agents):
        for b in agents[i + 1 :]:
            inter = agent_to_ids_map[a].intersection(agent_to_ids_map[b])
            yield f"{a} ∩ {b}: {len(inter)}"


def all_agents_intersection(agent_to_ids_map: Dict[str, Set[str]]) -> str:
    agents = sorted(agent_to_ids_map.keys())
    if not agents:
        return "Intersection of all agents: 0 (no agents)"

    inter = set(agent_to_ids_map[agents[0]])
    for agent in agents[1:]:
        inter &= agent_to_ids_map[agent]

    return f"Intersection of all agents ({', '.join(agents)}): {len(inter)}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Filter step3 JSON instances by minimum counts of "
            "valid_changed_expressions and valid_unchanged_expressions, "
            "and report per-agent removals and instance ID intersections."
        )
    )
    parser.add_argument(
        "--n-valid",
        type=int,
        default=1,
        help="Minimum number of valid_changed_expressions required to keep an instance.",
    )
    parser.add_argument(
        "--n-invalid",
        type=int,
        default=3,
        help="Minimum number of valid_unchanged_expressions required to keep an instance.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-3/step3.json"
        ),
        help="Path to input step3 JSON file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-3/step3-filtered.json"
        ),
        help="Path to write filtered JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    data = load_step3(args.input)
    filtered, removed_counts, total_counts = filter_instances(
        data, args.n_valid, args.n_invalid
    )

    # Write filtered JSON
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)

    print(f"Input file: {args.input}")
    print(f"Output file: {args.output}")
    print(f"n_valid (changed)  >= {args.n_valid}")
    print(f"n_invalid (unchanged) >= {args.n_invalid}")
    print()

    # Per-agent stats
    print("Per-agent instance counts:")
    for agent in sorted(total_counts.keys()):
        total = total_counts[agent]
        removed = removed_counts[agent]
        kept = total - removed
        print(f"- {agent}: total={total}, kept={kept}, removed={removed}")

    print()
    print("Pairwise intersections of instance_ids (after filtering):")
    ids_map = agent_to_ids(filtered)
    for line in pairwise_intersections(ids_map):
        print(line)

    print()
    print("All-agents intersection (after filtering):")
    print(all_agents_intersection(ids_map))


if __name__ == "__main__":
    main()

