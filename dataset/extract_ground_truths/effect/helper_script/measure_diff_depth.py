import argparse
import json
import re


def collect_paths(diff_entry):
    # case: values_changed, iterable_item_removed, etc
    if isinstance(diff_entry, dict):
        return [k for k in diff_entry.keys() if isinstance(k, str)]
    # case: dictionary_item_added, dictionary_iterm_removed
    if isinstance(diff_entry, (list, set, tuple)):
        return [x for x in diff_entry if isinstance(x, str)]
    return []


def _strip_quotes(text):
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def path_depth(path):
    segments = re.findall(r"\[(.*?)\]", path)
    if not segments:
        return 0
    cleaned = [_strip_quotes(s.strip()) for s in segments]
    if len(cleaned) == 1:
        return 1
    if len(cleaned) == 0:
        return 0
    return len(cleaned) - 1


def min_depth_for_diff(diff_dict):
    if not isinstance(diff_dict, dict):
        return None
    wildcard_mins = []
    for _, diff_entry in diff_dict.items():
        paths = collect_paths(diff_entry)
        if not paths:
            continue
        depths = [path_depth(p) for p in paths]
        wildcard_mins.append(min(depths))
    if not wildcard_mins:
        return None
    return min(wildcard_mins)


def process_file(input_path):
    with open(input_path, "r") as f:
        data = json.load(f)
    results = {}
    for agent, agent_data in data.items():
        agent_results = {}
        for instance_id, metadata in agent_data.items():
            if metadata == {}:
                agent_results[instance_id] = {}
                continue
            if metadata == None:
                agent_results[instance_id] = None
                continue
            diff_dict = metadata.get("diff")
            agent_results[instance_id] = min_depth_for_diff(diff_dict)
        results[agent] = agent_results
    return results


def depth_stats(results, threshold):
    stats = {}
    for agent, agent_results in results.items():
        total = 0
        below = 0
        none = 0
        empty = 0
        for depth in agent_results.values():
            if depth == None:
                none += 1
                continue
            if depth == {}:
                empty += 1
                continue
            total += 1
            if depth < threshold:
                below += 1
        stats[agent] = {
            "threshold": threshold,
            "below_threshold": below, # how many instances for that agent have a computed depth strictly less than the threshold.
            "total_valid": total, # how many instances had a valid depth (i.e., not None).
            "empty diff": empty, # how many instances are empty diff.
            "none metadata": none # how many instances are None (error when getting the delta behavior)
        }
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Compute minimum diff depth per agent/instance from a step1.json file."
    )
    parser.add_argument("--input", help="Path to step1.json")
    parser.add_argument(
        "-o",
        "--output",
        help="Optional output JSON path (prints to stdout if omitted).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        help="If set, print per-agent counts of depths below this threshold.",
    )
    args = parser.parse_args()

    results = process_file(args.input)
    if args.threshold is not None:
        stats = depth_stats(results, args.threshold)
        print(json.dumps(stats, indent=2))
        return
    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
    else:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
