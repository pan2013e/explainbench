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
                  "removals": {"start_line": 139, "count": 0},
                  "additions": {"start_line": 140, "count": 8}
                }
              ]
            }
          ]
    """
    # Regex to find file headers (--- a/... +++ b/...)
    file_header_pattern = re.compile(r'--- a/(.*?)\n\+\+\+ b/(.*?)\n', re.DOTALL)
    
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
            
            scope_name = ''
            func_match = func_pattern.match(context)
            if func_match:
                scope_name = func_match.group(1)
            else:
                class_match = class_pattern.match(context)
                if class_match:
                    scope_name = class_match.group(1)

            hunk_body_index = (i * 4) + 3
            hunk_body = hunk_contents[hunk_body_index]
            
            lines_in_hunk = hunk_body.split('\n')
            
            additions_count = sum(1 for line in lines_in_hunk if line.startswith('+'))
            removals_count = sum(1 for line in lines_in_hunk if line.startswith('-'))

            hunk_info = {
                "context": context,
                "scope_name": scope_name,
                "removals": {
                    "start_line": removal_start,
                    "count": removals_count
                },
                "additions": {
                    "start_line": addition_start,
                    "count": additions_count
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
    
    ground_truth_fnames = []
    for file_info in parsed_patch_data:
        hunk_info = file_info.get("hunks", [])
        if len(hunk_info) > 0:
            hunk_info = hunk_info[0]
            scope_name = hunk_info.get("scope_name", "")
            
            if scope_name != "":
                context = hunk_info.get("context")
                context = context.strip()
                scope_type = "function" if context.startswith("def ") else "class"

            ground_truth_fnames.append(
                (scope_name, scope_type)
            )
        
    return ground_truth_fnames
                
            
            