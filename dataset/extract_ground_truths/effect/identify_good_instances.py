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
    a summary JSON of the form:

        {agent: [instance_ids, ...]}
    """
    if argv is None:
        argv = sys.argv

    base_dir = Path(__file__).parent

    input_path = Path(argv[1])

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise SystemExit(f"{input_path} does not contain a top-level JSON object")

    bad_by_agent: dict[str, set[str]] = {}
    good_by_agent: dict[str, set[str]] = {}
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
                good_by_agent.setdefault(agent, set()).add(instance_id)
            else:
                bad_by_agent.setdefault(agent, set()).add(instance_id)

    output_mapping = {
        agent: sorted(list(instance_ids)) for agent, instance_ids in good_by_agent.items()
    }

    output_path = base_dir / "good_serialization_instances.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output_mapping, f, indent=2, sort_keys=True)
    agents_with_any = set(instances_per_agent.keys())

    print("=== Serialization report ===")
    print(f"Input JSON: {input_path}")
    print(f"Output JSON written to: {output_path}")
    print()
    print("Per-agent breakdown:")
    for agent in sorted(agents_with_any):
        bad_count = len(bad_by_agent.get(agent, set()))
        good_count = len(good_by_agent.get(agent, set()))
        total = instances_per_agent.get(agent, 0)
        print(f"  Agent: {agent}")
        print(f"    Total instances:             {total}")
        print(f"    Bad instances:               {bad_count}")
        print(f"    Good instances:              {good_count}")


if __name__ == "__main__":
    main()