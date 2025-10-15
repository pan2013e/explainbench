import json
import docker
import argparse
import re
from pathlib import Path
from typing import Dict, Tuple, Optional
from tqdm import tqdm

def find_common_files(item_input: Dict) -> Dict:
    """
    Finds pairs of old and new files with the same base name.
    Adds a 'common_files' key to the item dictionary.
    """
    item = item_input.copy()
    old_files = item.get("old_files", [])
    new_files = item.get("new_files", [])
    
    common_files = []
    new_files_map = {f.replace("new_", "").strip(): f for f in new_files}

    for old_file in old_files:
        base_name = old_file.replace("old_", "").strip()
        if base_name in new_files_map:
            new_file = new_files_map[base_name]
            common_files.append((old_file, new_file))
            
    item["common_files"] = common_files
    return item

def run_gumtree_diff(filepath_pair: Tuple[str, str]) -> Optional[str]:
    """
    Executes the Gumtree Docker command to diff two files and saves the output.
    """
    try:
        client = docker.from_env()
        left_file, right_file = filepath_pair

        left_file = filepath_pair[0]
        right_file = filepath_pair[1]
        
        output_path_str = left_file.replace("old_", "").strip()
        output_path_str = output_path_str.replace(".py", ".json")

        left_path = Path(left_file).resolve()
        right_path = Path(right_file).resolve()

        left_dir = str(left_path.parent)
        left_filename = left_path.name

        right_dir = str(right_path.parent)
        right_filename = right_path.name

        volumes = [
            f"{left_dir}:/left:ro",   # 'ro' for read-only
            f"{right_dir}:/right:ro"
        ]

        gumtree_command = [
            "textdiff",
            "-f", "JSON",
            f"/left/{left_filename}",
            f"/right/{right_filename}",
        ]

        print(f"Running container 'gumtreediff/gumtree' with command: {' '.join(gumtree_command)}")
        
        container_output = client.containers.run(
            image="gumtreediff/gumtree",
            command=gumtree_command,
            auto_remove=True,
            volumes=volumes,
            # ports={'4567/tcp': 4567} 
        )

        # breakpoint()
        decoded_output = container_output.decode('utf-8')      
        with open(output_path_str, mode="w", encoding='utf-8') as f:
            f.write(decoded_output)

        print(f"Success! Diff output saved to '{output_path_str}'")
        return output_path_str        
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        return None

def process_file(input_filepath: str) -> None:
    """
    Main processing function. Reads the input file line-by-line, processes each line,
    and writes the result immediately to an output file.
    """
    filepath = Path(input_filepath)
    output_filename = filepath.stem + "_gumtree.jsonl"
    
    print(f"Reading from '{filepath}' and writing to '{output_filename}'...")

    with open(filepath, 'r', encoding='utf-8') as f:
        total_lines = sum(1 for _ in f)

    with open(filepath, 'r', encoding='utf-8') as input_f, \
         open(output_filename, 'w', encoding='utf-8') as output_f:

        for line in tqdm(input_f, desc="Processing lines", total=total_lines, unit="line"):
            item = json.loads(line)
            # Step 1: Find common files for the current item
            item = find_common_files(item)
            
            # Step 2: Run Gumtree on common files and save output paths, with filtering
            gumtree_paths = []
            if "common_files" in item:
                for pair in item["common_files"]:
                    old_file, _ = pair
                    expected_output = old_file.replace("old_", "").strip()
                    expected_output = expected_output.replace(".py", ".json")
                    
                    # if Path(expected_output).exists():
                        # tqdm.write(f"Skipping (already exists): {expected_output}")
                        # gumtree_paths.append(expected_output)
                    # else:
                    output_path = run_gumtree_diff(pair)
                    if output_path:
                        gumtree_paths.append(output_path)
            
            item["gumtree_diff_files"] = gumtree_paths
            output_f.write(json.dumps(item) + '\n')

    print(f"\nProcessing complete. Results saved in '{output_filename}'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process a .jsonl file to run Gumtree diff on file pairs and save the output paths."
    )
    parser.add_argument(
        "--input_path",
        type=str,
        help="The path to the input .jsonl file."
    )
    
    args = parser.parse_args()
    process_file(args.input_path)
