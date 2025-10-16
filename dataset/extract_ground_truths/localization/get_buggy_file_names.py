import os
import json
from typing import Dict, Any

def get_buggy_filenames(record: Dict[str, Any], dataset_dir: str) -> Dict[str, Any]:
    """
    Get the filenames from the buggy function names
    """
    gumtree_files = record.get("gumtree_files", [])
    buggy_filenames = []
    for path in gumtree_files:
        full_path = os.path.join(dataset_dir, path) 
        with open(full_path, "r") as f:
            gumtree = json.load(f) 
            actions = gumtree.get("actions", [])
            if actions:
                path = path.split("/")[1:]
                path = "/".join(path)
                path = path[:-5]
                path += ".py"
                buggy_filenames.append(path)
    record["buggy_file_names"] = buggy_filenames
    return record