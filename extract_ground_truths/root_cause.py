import re
from typing import List

def extract_modified_files(patch_content: str) -> List[str]:
    """
    Parses a diff/patch content and extracts the unique list of modified file paths.
    """
    pattern = r"^(?:--- a/|\+\+\+ b/)(?!/dev/null)([^\t\n]+)"
    matches = re.findall(pattern, patch_content, re.MULTILINE)
    
    # Convert to a set to get unique file paths, then convert back to a list.
    unique_files = list(set(matches))
    return unique_files

