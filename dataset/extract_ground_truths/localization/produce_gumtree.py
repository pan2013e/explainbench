import json
import docker
import argparse
from pathlib import Path
from typing import Dict, Tuple, Optional
from tqdm import tqdm
from multiprocessing import Pool, cpu_count

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

def process_single_item(line: str) -> str:
    """
    Processes a single JSONL line: finds common files, runs Gumtree diffs,
    and returns the updated item as a JSON string.
    """
    try:
        item = json.loads(line)
        item = find_common_files(item)

        gumtree_paths = []
        if "common_files" in item and item["common_files"]:
            for pair in item["common_files"]:
                output_path = run_gumtree_diff(pair)
                if output_path:
                    gumtree_paths.append(output_path)
        item["gumtree_diff_files"] = gumtree_paths
        return json.dumps(item)
    except Exception as e:
        print(f"Error processing line: {e}")
        return json.dumps({"error": str(e)})

def process_file(input_filepath: str) -> None:
    """
    Processes multiple lines in parallel using multiprocessing.
    """
    filepath = Path(input_filepath)
    output_filename = filepath.stem + "_gumtree.jsonl"

    print(f"Reading from '{filepath}' and writing to '{output_filename}'...")

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    total_lines = len(lines)
    num_workers = min(cpu_count(), 16)

    with Pool(processes=num_workers) as pool:
        results = list(
            tqdm(
                pool.imap(process_single_item, lines),
                total=total_lines,
                desc="Processing lines in parallel",
                unit="line"
            )
        )

    # Write all outputs sequentially
    with open(output_filename, 'w', encoding='utf-8') as output_f:
        for result in results:
            output_f.write(result + '\n')

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
