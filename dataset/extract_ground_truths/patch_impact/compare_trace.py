#!/usr/bin/env python3
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    """Read a JSONL file into a list of dicts."""
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save_jsonl(data: List[Dict[str, Any]], path: str):
    """Write list of dicts to a JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for obj in data:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def get_event_key(event: Dict[str, Any]) -> tuple:
    """Return a key representing a program location."""
    return (
        event.get("filepath"),
        event.get("line_number"),
        event.get("statement"),
        event.get("function_name"),
        event.get("event_type"),
    )

def normalize(value: Any) -> Any:
    """Recursively normalize values for order-insensitive comparison."""
    if isinstance(value, list):
        return tuple(sorted(json.dumps(normalize(v), sort_keys=True) for v in value))
    elif isinstance(value, dict):
        return tuple(sorted(
            (k, json.dumps(normalize(v), sort_keys=True)) for k, v in value.items()
        ))
    else:
        return value


def compare_runtime_fields(ev1: Dict[str, Any], ev2: Dict[str, Any]) -> bool:
    """Return True if runtime fields differ (order-insensitive)."""
    runtime_fields = ["vars_defined", "vars_used", "seen_variables", "parameters"]
    for field in runtime_fields:
        if normalize(ev1.get(field)) != normalize(ev2.get(field)):
            return True
    return False


def compare_traces(buggy_path: str, fixed_path: str):
    """
    Compare two execution traces and write the unique/behavior-diff results.
    """
    buggy_events = load_jsonl(buggy_path)
    fixed_events = load_jsonl(fixed_path)

    # Track how many times we've seen each location (for nth occurrence), to handle if a line is executed multiple lines. Using event_id is too strict
    buggy_counts = defaultdict(int)
    fixed_counts = defaultdict(int)

    # Build indexed lists with occurrence index
    def with_occurrences(events, counter):
        indexed = []
        for ev in events:
            key = get_event_key(ev)
            counter[key] += 1
            ev["_occurrence"] = counter[key]
            indexed.append(ev)
        return indexed

    buggy_events = with_occurrences(buggy_events, buggy_counts)
    fixed_events = with_occurrences(fixed_events, fixed_counts)

    # Build quick lookup for fixed events
    fixed_index = {
        (get_event_key(ev), ev["_occurrence"]): ev for ev in fixed_events
    }

    buggy_unique, fixed_unique = [], []
    matched_keys = set()

    for be in buggy_events:
        key = (get_event_key(be), be["_occurrence"])
        fe = fixed_index.get(key)
        if not fe:
            be["diff_type"] = "unique"
            buggy_unique.append(be)
        else:
            matched_keys.add(key)
            if compare_runtime_fields(be, fe):
                be["diff_type"] = "behavior_diff"
                fe["diff_type"] = "behavior_diff"
                buggy_unique.append(be)
                fixed_unique.append(fe)

    # Add unmatched fixed events
    for fe in fixed_events:
        key = (get_event_key(fe), fe["_occurrence"])
        if key not in matched_keys and key not in fixed_index:
            continue  
        if key not in matched_keys:
            fe["diff_type"] = "unique"
            fixed_unique.append(fe)

    buggy_out = str(Path(buggy_path).with_name("buggy_trace_unique.jsonl"))
    fixed_out = str(Path(fixed_path).with_name("fixed_trace_unique.jsonl"))
    save_jsonl(buggy_unique, buggy_out)
    save_jsonl(fixed_unique, fixed_out)

    print(f"Saved unique buggy trace: {buggy_out}")
    print(f"Saved unique fixed trace: {fixed_out}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compare buggy and fixed execution traces.")
    parser.add_argument("--buggy", required=True, help="Path to buggy trace JSONL file")
    parser.add_argument("--fixed", required=True, help="Path to fixed trace JSONL file")
    args = parser.parse_args()

    compare_traces(args.buggy, args.fixed)
