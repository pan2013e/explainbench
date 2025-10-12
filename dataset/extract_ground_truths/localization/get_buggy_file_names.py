from typing import Dict, Any


def get_buggy_filenames(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get the filenames from the buggy function names
    """
    
    buggy_items = record.get("buggy_function_names", [])
    output = set([])
    for item in buggy_items:
        parts = item.split("::", 1)
        buggy_filename = parts[0]
        output.add(buggy_filename)
    record["buggy_file_names"] = list(output)
    return record