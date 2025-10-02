import re
import pprint
from typing import Dict, List, Tuple

def parse_patch(patch_content: str)->List[Dict]:
    """
    Parses a patch file content and extracts metadata about the changes.

    Args:
        patch_content (str): A string containing the full content of a patch file.

    Returns:
        list: A list of dict containing the changed files, where each file
              has details about the hunks of changes within it.
        
        Example Return Structure:
        [
            {
              "old_path": "a/path/to/old_file.py",
              "new_path": "b/path/to/new_file.py",
              "is_new_file": False,
              "is_deleted_file": False,
              "hunks": [
                {
                  "context": "def function_name(args)",
                  "scope_name": "function_name",
                  "removals": {"start_line": 139, "count": 0, "line_numbers": []},
                  "additions": {"start_line": 140, "count": 8, "line_numbers": [140, 141, 142, 143, 144, 145, 146, 147]}
                }
              ]
            }
          ]
    """
    # Regex to find file headers (--- a/... +++ b/...)
    # The prefixes `a/` and `b/` are in optional, non-capturing groups.
    # (?:a/)?  => Match "a/" zero or one time, but don't capture it.
    # (.*?)    => This becomes capture group 1 (the actual path).
    file_header_pattern = re.compile(r'--- (?:a/)?(.*?)\n\+\+\+ (?:b/)?(.*?)\n')
    
    # Regex to find hunk headers (@@ -start,count +start,count @@ context)
    hunk_header_pattern = re.compile(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*?)\n')
    
    # Regex to find function or class names from a context line
    func_pattern = re.compile(r'^(?:async\s+)?def\s+([a-zA-Z_]\w*)')
    class_pattern = re.compile(r'^class\s+([a-zA-Z_]\w*)')

    result = []
    
    # Split the patch by 'diff --git' to process one file change at a time
    file_patches = patch_content.split('diff --git ')[1:]

    for file_patch in file_patches:
        file_header_match = file_header_pattern.search(file_patch)
        if not file_header_match:
            continue

        old_path = file_header_match.group(1)
        new_path = file_header_match.group(2)
        
        file_info = {
            "old_path": old_path,
            "new_path": new_path,
            "is_new_file": old_path == "/dev/null",
            "is_deleted_file": new_path == "/dev/null",
            "hunks": []
        }

        # Find all hunks within the current file patch
        hunks = hunk_header_pattern.finditer(file_patch)
        hunk_contents = hunk_header_pattern.split(file_patch)[1:]

        for i, hunk_match in enumerate(hunks):
            removal_start = int(hunk_match.group(1))
            addition_start = int(hunk_match.group(2))
            context = hunk_match.group(3).strip()
            
            scope_info = {"name": "", "type": ""}
            func_match = func_pattern.match(context)
            if func_match:
                scope_info["name"] = func_match.group(1)
                scope_info["type"] = "function"
            else:
                class_match = class_pattern.match(context)
                if class_match:
                    scope_info["name"] = class_match.group(1)
                    scope_info["type"] = "class"

            hunk_body_index = (i * 4) + 3
            hunk_body = hunk_contents[hunk_body_index]
            
            lines_in_hunk = hunk_body.split('\n')
            
            if not scope_info["name"]:
                for line in lines_in_hunk:
                    if line.startswith(('+', '-')):
                        code_line = line[1:].strip()
                        
                        func_match = func_pattern.match(code_line)
                        if func_match:
                            # Change: Populate scope_info dictionary and break
                            scope_info["name"] = func_match.group(1)
                            scope_info["type"] = "function"
                            break

                        class_match = class_pattern.match(code_line)
                        if class_match:
                            # Change: Populate scope_info dictionary and break
                            scope_info["name"] = class_match.group(1)
                            scope_info["type"] = "class"
                            break
            
            # Track line numbers for additions and removals
            old_line_num = removal_start
            new_line_num = addition_start
            removal_line_numbers = []
            addition_line_numbers = []
            removal_lines_content = []
            addition_lines_content = []
            for line in lines_in_hunk:
                content = line[1:].strip()
                if line.startswith('-'):
                    if content:
                        removal_line_numbers.append(old_line_num)
                        removal_lines_content.append(content)
                        old_line_num += 1
                elif line.startswith('+'):
                    if content:
                        addition_line_numbers.append(new_line_num)
                        addition_lines_content.append(content)
                        new_line_num += 1
                elif line.startswith(' '):
                    # Context line - exists in both old and new
                    old_line_num += 1
                    new_line_num += 1
            
            additions_count = len(addition_line_numbers)
            removals_count = len(removal_line_numbers)

            hunk_info = {
                "context": context,
                "scope": scope_info,
                "removals": {
                    "start_line": removal_start,
                    "count": removals_count,
                    "line_numbers": removal_line_numbers,
                    "lines": removal_lines_content
                },
                "additions": {
                    "start_line": addition_start,
                    "count": additions_count,
                    "line_numbers": addition_line_numbers,
                    "lines": addition_lines_content
                }
            }
            file_info["hunks"].append(hunk_info)

        result.append(file_info)

    return result

def extract_buggy_filenames(parsed_patch_data: List[Dict]) -> List[str]:
    """
    Extract the filenames from the parsed patch data.
    """
    
    ground_truth_filepaths = []
    for file_info in parsed_patch_data:
        
        # avoid new created file
        is_new_file = file_info.get("is_new_file")
        if not is_new_file:
            filename = file_info.get("old_path", "")
            assert filename != ""
            
            ground_truth_filepaths.append(filename)
    return ground_truth_filepaths   

def extract_buggy_function_names(parsed_patch_data: List[Dict]) -> List[Tuple[str, str]]:
    """
    Extract the buggy function names from the parsed patch data.
    """
    buggy_scopes = set()
    for file_info in parsed_patch_data:
        for hunk in file_info.get("hunks", []):
            scope_info = hunk.get("scope", {})
            scope_name = scope_info.get("name")
            scope_type = scope_info.get("type")
            is_new_file = file_info.get("is_new_file")
            if scope_name and not is_new_file:
                buggy_scopes.add((scope_name, scope_type))

    # Convert the set of tuples back to a list for the final return value
    return list(buggy_scopes)
                
def extract_new_created_filenames(parsed_patch_data: List[Dict]) -> List[str]:
    """
    Extract the filenames from the files that are newly created from the parsed patch data.
    """
    
    ground_truth_filepaths = []
    for file_info in parsed_patch_data:
        is_new_file = file_info.get("is_new_file")
        if is_new_file:
            filename = file_info.get("new_path", "")
            assert filename != ""
            
            ground_truth_filepaths.append(filename)
    return ground_truth_filepaths

def extract_deleted_filenames(parsed_patch_data: List[Dict]) -> List[str]:
    """
    Extract the filenames from the files that are deleted from the parsed patch data.
    """
    
    ground_truth_filepaths = []
    for file_info in parsed_patch_data:
        is_deleted_file = file_info.get("is_deleted_file")
        if is_deleted_file:
            filename = file_info.get("old_path", "")
            assert filename != ""
            
            ground_truth_filepaths.append(filename)
    return ground_truth_filepaths

def extract_buggy_line_numbers(parsed_patch_data: List[Dict]) -> Dict[str, int]:
    """
    Extract the buggy line numbers. The buggy line numbers are those with a prefix "-".
    """
    
    ground_truths = {}
    for file_info in parsed_patch_data:
        is_new_file = file_info.get("is_new_file")
        
        if not is_new_file:
            filename = file_info.get("old_path", "")
            assert filename != ""
                        
            hunk_list = file_info.get("hunks", [])
            
            if len(hunk_list) > 0:
                for hunk_info in hunk_list:
                    removals = hunk_info.get("removals", [])
                    
                    if len(removals) > 0:
                        removed_lines = removals.get("line_numbers")
                        if filename not in ground_truths:
                            ground_truths[filename] = []

                        ground_truths[filename].extend(removed_lines)
    ground_truths = [(k, v) for k, v in ground_truths.items() if v]
    return ground_truths