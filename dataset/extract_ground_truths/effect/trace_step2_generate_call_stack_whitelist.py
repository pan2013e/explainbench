import os
import argparse
import json

from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set

from execution.util import get_instance_ids

DIR = Path(__file__).parent.resolve()

def load_jsonl(path: str) -> Iterable[dict]:
    """Yield JSON objects, one per line, from a JSONL file."""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def collect_functions_by_target(
    jsonl_path: str, target_qualnames: Iterable[str]
) -> Dict[str, Set[str]]:
    """
    For each target qualname, collect the union of all function qualnames
    that appear in stacks for that target.

    Returns:
        dict: target_qualname -> set of function qualnames
    """
    targets_set: Set[str] = set(target_qualnames)
    results: Dict[str, Set[str]] = defaultdict(set)

    for entry in load_jsonl(jsonl_path):
        target = entry.get("target")
        if target not in targets_set:
            continue

        stack = entry.get("stack") or []
        for frame in stack:
            # frame is expected to be [module, qualname, ...]
            if len(frame) < 2:
                continue
            _, qualname = frame[0], frame[1]
            results[target].add(qualname)
    return results


def collect_files(root_path: Path, keyword_filter: str = "") -> List[Path]:
    jsonl_files = root_path.rglob("*.jsonl")
    if keyword_filter:
        return [x for x in jsonl_files if keyword_filter in str(x)]
    return list(jsonl_files)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Use precomputed target qualnames (from a JSON file) to "
            "filter buggy/patched trace JSONLs and collect function qualnames."
        )
    )

    parser.add_argument(
        "--root-path",
        type=str,
        default=f"../../../logs/run_evaluation/track.{{agent_name}}.{os.getuid()}/{{agent_name}}/{{instance_id}}",
        help="Template path to logs; must contain {agent_name} and {instance_id}.",
    )

    parser.add_argument(
        "--agents",
        nargs="+",
        default=[
            "gold",
            "20250603_Refact_Agent_claude-4-sonnet",
            "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
            "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
            "20250928_trae_doubao_seed_code",
            "20250807_mini-v1.7.0_gpt-5-mini",
        ],
        help="List of agent names to process.",
    )

    parser.add_argument(
        "--instance-ids",
        nargs="+",
        default=["all"],
        help=(
            "Optional list of instance_ids to process. "
            "If omitted, all instance_ids found for each agent in --targets-json are used."
        ),
    )

    parser.add_argument(
        "--targets-json",
        type=Path,
        default=DIR / "../../../execution/allowed_qualnames.json",
        help=(
            "Path to JSON produced by the previous step, with structure:\n"
            "  { agent_name: { instance_id: [list of target qualnames] } }"
        ),
    )

    parser.add_argument(
        "--output-path",
        type=Path,
        default=DIR / "../../../execution/allowed_functions.json",
        help="Path to the output JSON file.",
    )

    args = parser.parse_args()

    ROOT_PATH = args.root_path
    AGENT_NAMES = args.agents
    INSTANCE_IDS_ARG = get_instance_ids(args.instance_ids)
    TARGETS_JSON = args.targets_json
    OUTPUT_PATH = args.output_path

    # Load precomputed targets: agent -> instance_id -> [target_qualnames]
    with TARGETS_JSON.open("r", encoding="utf-8") as f:
        targets_data: Dict[str, Dict[str, List[str]]] = json.load(f)

    # Final structure: agent -> instance_id -> [functions]
    results: Dict[str, Dict[str, List[str]]] = {}

    for agent in AGENT_NAMES:
        print(f"Processing agent: {agent}")
        agent_mapping: Dict[str, List[str]] = {}

        agent_targets: Dict[str, List[str]] = targets_data.get(agent, {})
        if not agent_targets:
            print(f"  [warn] No targets found for agent '{agent}' in {TARGETS_JSON}")
            results[agent] = {}
            continue
        if INSTANCE_IDS_ARG:
            instance_ids = INSTANCE_IDS_ARG
        else:
            instance_ids = sorted(agent_targets.keys())

        for instance_id in instance_ids:
            target_qualnames = agent_targets.get(instance_id)
            if not target_qualnames:
                print(f"  [warn] No target qualnames for {agent}/{instance_id}, skipping.")
                continue

            current_root = DIR / ROOT_PATH.format(agent_name=agent, instance_id=instance_id)

            buggy_files = collect_files(current_root, "buggy_traces")
            patched_files = collect_files(current_root, "patched_traces")

            if not buggy_files or not patched_files:
                print(f"  [warn] No buggy/patched trace files for {agent}/{instance_id}, skipping.")
                agent_mapping[instance_id] = []
                continue

            all_functions: Set[str] = set()

            # Use the same target_qualnames for both buggy and patched traces
            for jsonl_path in buggy_files:
                per_target = collect_functions_by_target(
                    jsonl_path=str(jsonl_path),
                    target_qualnames=target_qualnames,
                )
                for funcs in per_target.values():
                    all_functions.update(funcs)

            for jsonl_path in patched_files:
                per_target = collect_functions_by_target(
                    jsonl_path=str(jsonl_path),
                    target_qualnames=target_qualnames,
                )
                for funcs in per_target.values():
                    all_functions.update(funcs)

            agent_mapping[instance_id] = sorted(all_functions)
            print(f"  {instance_id}: {len(all_functions)} functions")

        results[agent] = agent_mapping

    # Write out the final JSON
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=True)

    print(f"Wrote functions JSON to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
