#!/usr/bin/env python

import argparse
import itertools
import json
from pathlib import Path
from typing import Dict, Iterable, Set


def load_instance_ids(path: Path) -> Dict[str, Set[str]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    agent_to_ids: Dict[str, Set[str]] = {}
    for agent, instances in data.items():
        if isinstance(instances, dict):
            agent_to_ids[agent] = set(instances.keys())

    return agent_to_ids


def compute_pairwise_intersections(agent_to_ids: Dict[str, Set[str]]) -> Iterable[str]:
    agents = sorted(agent_to_ids.keys())
    for a, b in itertools.combinations(agents, 2):
        inter = agent_to_ids[a].intersection(agent_to_ids[b])
        yield f"{a} ∩ {b}: {len(inter)}"


def compute_all_intersection(agent_to_ids: Dict[str, Set[str]]) -> str:
    agents = sorted(agent_to_ids.keys())
    if not agents:
        return "No agents found."

    iterator = iter(agents)
    first_agent = next(iterator)
    inter = set(agent_to_ids[first_agent])
    for agent in iterator:
        inter &= agent_to_ids[agent]

    return f"Intersection of all agents ({', '.join(agents)}): {len(inter)}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute intersections between instance IDs in a step JSON file."
    )
    parser.add_argument(
        "json_path",
        type=Path,
        help="Path to step JSON (e.g., step1-filtered.json).",
    )
    args = parser.parse_args()

    agent_to_ids = load_instance_ids(args.json_path)

    print(f"Loaded {len(agent_to_ids)} agents from {args.json_path}")
    for agent, ids in sorted(agent_to_ids.items()):
        print(f"{agent}: {len(ids)} instance_ids")

    print("\nPairwise intersections:")
    for line in compute_pairwise_intersections(agent_to_ids):
        print(line)

    print("\nAll-agents intersection:")
    print(compute_all_intersection(agent_to_ids))


if __name__ == "__main__":
    main()

