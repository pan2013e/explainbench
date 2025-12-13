import json
import sys
from pathlib import Path


def is_good(value) -> bool:
    """
    Return True if the JSON-serialized value satisfies the
    \"good\" size criterion (naming is misleading on purpose).
    """
    serialized = json.dumps(value)
    return len(serialized) < 500


def main(argv: list[str] | None = None) -> None:
    """
    Given a single JSON file with structure:

        {
          "gold": {instance_id: {...}},
          "agent_a": {instance_id: {...}},
          "agent_b": {instance_id: {...}},
          ...
        }

    identify instances with oversized serialized variables and write 
    a JSONL file where each line is the original per-instance
    metadata record, filtered to only include \"good\" instances.
    """
    if argv is None:
        argv = sys.argv

    input_path = Path(argv[1])
    base_dir = input_path.parent

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise SystemExit(f"{input_path} does not contain a top-level JSON object")

    bad_by_agent: dict[str, set[str]] = {}
    good_instances: dict[str, dict[str, dict]] = {}
    instances_per_agent: dict[str, int] = {}

    for agent, instances in data.items():
        if not isinstance(instances, dict):
            continue

        for instance_id, entry in instances.items():
            instances_per_agent[agent] = instances_per_agent.get(agent, 0) + 1

            if not entry:
                bad_by_agent.setdefault(agent, set()).add(instance_id)
                continue

            all_good = True

            # An instance is \"good\" only if *all* relevant values
            # satisfy `is_good` (our good criterion).
            for section in ("buggy_variable", "patched_variable"):
                section_vals = entry.get(section, {})
                if isinstance(section_vals, dict):
                    for _, val in section_vals.items():
                        if not is_good(val):
                            all_good = False

            if all_good:
                good_instances.setdefault(agent, {})[instance_id] = entry
            else:
                bad_by_agent.setdefault(agent, set()).add(instance_id)

    # Also write a JSONL file with one record per (agent, instance_id),
    # preserving the original metadata structure.
    jsonl_path = base_dir / "step1-filtered.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for agent, instances in sorted(good_instances.items()):
            for instance_id, entry in sorted(instances.items()):
                record = dict(entry)
                # Ensure instance_id/agent are present in the record.
                record.setdefault("instance_id", instance_id)
                record.setdefault("agent", agent)
                f.write(json.dumps(record) + "\n")
    agents_with_any = set(instances_per_agent.keys())

    print("=== Serialization report ===")
    print(f"Input JSON: {input_path}")
    print(f"Output JSONL written to: {jsonl_path}")
    print()
    print("Per-agent breakdown:")
    for agent in sorted(agents_with_any):
        bad_count = len(bad_by_agent.get(agent, set()))
        good_count = len(good_instances.get(agent, {}))
        total = instances_per_agent.get(agent, 0)
        print(f"  Agent: {agent}")
        print(f"    Total instances:             {total}")
        print(f"    Bad instances:               {bad_count}")
        print(f"    Good instances:              {good_count}")


if __name__ == "__main__":
    main()
