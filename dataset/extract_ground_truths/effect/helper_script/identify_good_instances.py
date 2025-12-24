import json
import sys
from pathlib import Path

from execution.util import EXCLUDED_IDS

def contains_datetime_object(value) -> bool:
    """
    Recursively check whether a (possibly nested) JSON-like structure
    contains a dict with {"py/object": "datetime.datetime"}.
    """
    if isinstance(value, dict):
        if value.get("py/object") == "datetime.datetime":
            return True
        return any(contains_datetime_object(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_datetime_object(v) for v in value)
    return False

def is_var_good(value) -> bool:
    """
    Return True if the JSON-serialized value satisfies the
    \"good\" size criterion (naming is misleading on purpose).
    """
    serialized = json.dumps(value)
    return len(serialized) < 4000

def is_input_param_good(value) -> bool:
    serialized = json.dumps(value)
    return len(serialized) < 8000

def is_contains_password(value) -> bool:
    serialized = json.dumps(value)
    return "password" in serialized.lower()

def is_contains_tmpdir(value) -> bool:
    serialized = json.dumps(value)
    return "/tmp" in serialized.lower() and "/tmp/pytest-of-" not in serialized.lower()

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
    a JSON file that preserves the original structure:

        {
          agent: {
            instance_id: {...},  # original metadata entry
            ...
          },
          ...
        }

    but filtered to only include \"good\" instances.
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
    # This will be written out as JSON: it includes all instance IDs.
    # Good instances keep their full metadata; bad instances get {}.
    output_instances: dict[str, dict[str, dict]] = {}
    instances_per_agent: dict[str, int] = {}
    pmf_stats: dict[tuple[str, str, str], int] = {}

    for agent, instances in data.items():
        if not isinstance(instances, dict):
            continue

        for instance_id, entry in instances.items():
            instances_per_agent[agent] = instances_per_agent.get(agent, 0) + 1

            if entry is None:
                bad_by_agent.setdefault(agent, set()).add(instance_id)
                output_instances.setdefault(agent, {})[instance_id] = None
                continue

            if entry == {}:
                bad_by_agent.setdefault(agent, set()).add(instance_id)
                output_instances.setdefault(agent, {})[instance_id] = {}
                continue

            # Track distribution of PMF / event types.
            pmf_val = entry.get("seen_pmf")
            buggy_type = entry.get("buggy_event_type")
            patched_type = entry.get("patched_event_type")
            key = (str(pmf_val), str(buggy_type), str(patched_type))
            pmf_stats[key] = pmf_stats.get(key, 0) + 1

            all_good = True

            # An instance is \"good\" only if *all* relevant values
            # satisfy `is_good` (our good criterion).
            for section in ("buggy_variables", "patched_variables"):
                section_vals = entry.get(section, {})
                if isinstance(section_vals, dict):
                    for _, val in section_vals.items():
                        if not is_var_good(val):
                            all_good = False
                    if contains_datetime_object(section_vals) or is_contains_password(section_vals) or is_contains_tmpdir(section_vals):
                        all_good = False

            for section in ("buggy_function_param", "patched_function_param"):
                section_vals = entry.get(section, {})
                if isinstance(section_vals, dict):
                    for _, val in section_vals.items():
                        if not is_input_param_good(val):
                            all_good = False

            # If either event type is a line event, require that we
            # have seen a PMF; otherwise mark the instance as bad.
            if (
                entry.get("buggy_event_type") == "Line"
                or entry.get("patched_event_type") == "Line"
            ):
                if not entry.get("seen_pmf"):
                    all_good = False

            if all_good:
                good_instances.setdefault(agent, {})[instance_id] = entry
                output_instances.setdefault(agent, {})[instance_id] = entry
            else:
                bad_by_agent.setdefault(agent, set()).add(instance_id)
                output_instances.setdefault(agent, {})[instance_id] = None
            
            if not all_good:
                if instance_id not in EXCLUDED_IDS:
                    print(instance_id)

    json_path = base_dir / "step1-filtered.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(output_instances, f, indent=2, sort_keys=True)
    agents_with_any = set(instances_per_agent.keys())

    print("=== Serialization report ===")
    print(f"Input JSON: {input_path}")
    print(f"Output JSON written to: {json_path}")
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

    print()
    print("PMF / event type stats:")
    for (pmf_val, buggy_type, patched_type), count in sorted(pmf_stats.items()):
        print(
            f"  seen_pmf={pmf_val!r}, "
            f"buggy_event_type={buggy_type!r}, "
            f"patched_event_type={patched_type!r}: {count}"
        )


if __name__ == "__main__":
    main()
