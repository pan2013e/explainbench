from typing import List, Dict

def remove_indentation(input_text: str) -> str:
    """
    Removes leading spaces and tabs from each line in the input text.
    """
    lines = input_text.splitlines()
    stripped_lines = [line.lstrip() for line in lines]
    return "\n".join(stripped_lines)

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