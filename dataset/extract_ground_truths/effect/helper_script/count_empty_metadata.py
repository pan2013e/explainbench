import json
from pathlib import Path
from collections import defaultdict

from execution.util import EXCLUDED_IDS

path = Path("/home/yusuf/explainbench/shared_logs/logs/run_evaluation/output_per_step-3/step1.json")

with path.open() as f:
    data = json.load(f)

empty_none_per_agent = defaultdict(int)
empty_dict_per_agent = defaultdict(int)
total_per_agent = {}

# data structure: {agent: {instance_id: metadata}}
for agent, instances in data.items():
    if not isinstance(instances, dict):
        continue

    filtered_total = 0

    for instance_id, metadata in instances.items():
        if instance_id in EXCLUDED_IDS:
            continue
        filtered_total += 1
        if metadata is None:
            print(instance_id)
            empty_none_per_agent[agent] += 1
        elif metadata == {}:
            empty_dict_per_agent[agent] += 1

    total_per_agent[agent] = filtered_total

non_empty_per_agent = {}
for agent in total_per_agent:
    non_empty_per_agent[agent] = (
        total_per_agent[agent]
        - empty_none_per_agent[agent]
        - empty_dict_per_agent[agent]
    )

print("Empty dict metadata counts per agent:")
for agent in sorted(total_per_agent):
    print(f"- {agent}: {empty_dict_per_agent[agent]} empty dict out of {total_per_agent[agent]} instances")

print("\nNone metadata counts per agent (treated as errors):")
for agent in sorted(total_per_agent):
    print(f"- {agent}: {empty_none_per_agent[agent]} None out of {total_per_agent[agent]} instances")

print("\nValid metadata counts per agent:")
for agent in sorted(total_per_agent):
    print(f"- {agent}: {non_empty_per_agent[agent]} non-empty out of {total_per_agent[agent]} instances")
