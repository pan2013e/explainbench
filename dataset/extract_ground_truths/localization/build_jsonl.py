import os
import json
import argparse
from typing import List, Dict, Any
from collections import defaultdict

from extract_ground_truths.localization.get_class_func_context import process_instance

def build_ground_truth_instances(dataset_dir: str) -> List[Dict[str, Any]]:
    """
    Scans a directory to create a ground_truth.jsonl file.
    """
    print(f"Scanning directory: {dataset_dir}")
    # print(f"Writing output to: {output_file}")

    instance_data = defaultdict(lambda: {"before": [], "after": [], "gumtree": []})
    for root, _, files in os.walk(dataset_dir):
        for filename in files:
            if filename.startswith('old_') and filename.endswith('.py'):
                
                base_name = filename[4:]  # Remove 'old_' prefix (e.g., "misc.py")
                expected_after_file = f"new_{base_name}"
                expected_json_file = base_name.replace('.py', '.json')

                if expected_after_file in files and expected_json_file in files:
                    
                    relative_path_from_root = os.path.relpath(root, dataset_dir)
                    instance_id = relative_path_from_root.split(os.sep)[0]
                    
                    before_path = os.path.join(relative_path_from_root, filename)
                    after_path = os.path.join(relative_path_from_root, expected_after_file)
                    gumtree_path = os.path.join(relative_path_from_root, expected_json_file)

                    instance_data[instance_id]["before"].append(before_path)
                    instance_data[instance_id]["after"].append(after_path)
                    instance_data[instance_id]["gumtree"].append(gumtree_path)

    instances = []
    for instance_id in sorted(instance_data.keys()):
        data = instance_data[instance_id]
        record = {
            "instance_id": instance_id,
            "files_before": sorted(data["before"]), # Sort file lists for consistency
            "files_after": sorted(data["after"]),
            "gumtree_files": sorted(data["gumtree"])
        }
        record = process_instance(record, dataset_dir)
        instances.append(record)
        
    return instances


def main():
    """Main function to parse arguments and run the script."""
    parser = argparse.ArgumentParser(
        description="Scan a directory and create a ground_truth.jsonl file."
    )
    parser.add_argument(
        "-i", "--input_dir",
        help="Path to the root directory of the dataset (e.g., 'swe_bench_files')."
    )
    parser.add_argument(
        "-o", "--output_file",
        default="ground_truth.jsonl",
        help="Path to the output .jsonl file (default: ground_truth.jsonl)."
    )
    args = parser.parse_args()

    all_records = build_ground_truth_instances(args.input_dir)

    print(f"Found {len(all_records)} instances.")
    print(f"Writing records to {args.output_file}...")
    
    with open(args.output_file, 'w') as f:
        for record in all_records:
            f.write(json.dumps(record) + '\n')

    print("Done.")

if __name__ == "__main__":
    main()