from typing import List, Dict
import docker
from pathlib import Path

def remove_indentation(input_text: str) -> str:
    """
    Removes leading spaces and tabs from each line in the input text.
    """
    lines = input_text.splitlines()
    stripped_lines = [line.lstrip() for line in lines]
    return "\n".join(stripped_lines)

def run_gumtree_diff(left_file: str, right_file: str, output_file: str)->bool:
    """
    Executes the Gumtree Docker command to diff two files and save the output.
    """
    try:
        client = docker.from_env()
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

        decoded_output = container_output.decode('utf-8')      
        with open(output_file, mode="w", encoding='utf-8') as f:
            f.write(decoded_output)

        print(f"Success! Diff output saved to '{output_file}'")
        return True
        
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False

def count_empty_scopes(parsed_patch_data: List[Dict]) -> int:
    """
    Counts the number of hunks with an empty scope name in parsed patch data.

    Args:
        parsed_patch_data (List[Dict]): The list of dictionaries returned
                                         by the `parse_patch` function.

    Returns:
        int: The total count of hunks where the scope name is an empty string.
    """
    empty_scope_count = 0

    for file_info in parsed_patch_data:
        for hunk in file_info.get("hunks", []):
            scope_info = hunk.get("scope", {})
            scope_name = scope_info.get("name")
            if not scope_name:
                empty_scope_count += 1

    return empty_scope_count

def count_all_hunks(parsed_patch_data: List[Dict]) -> int:
    """
    Counts the number of hunks in parsed patch data.

    Args:
        parsed_patch_data (List[Dict]): The list of dictionaries returned
                                         by the `parse_patch` function.

    Returns:
        int: The total count of hunks.
    """
    scope_count = 0

    for file_info in parsed_patch_data:
        scope_count += len(file_info.get("hunks", []))
    return scope_count