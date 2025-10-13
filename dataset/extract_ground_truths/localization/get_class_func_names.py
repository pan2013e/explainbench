import ast
import json
from typing import List, Tuple, Dict, Any
from pathlib import Path

from dataset.extract_ground_truths.diff_analyzer import TreeQuery, GumTreeAction, CodeVisitor, find_enclosing_scopes

def identify_context(path_before: str, path_after: str, path_gumtree: str) -> List[Tuple[str, str]]:
    """
    Analyzes a single file change to identify all modified functions and classes.
    """
    with open(path_before, 'r', encoding='utf-8') as f:
        before_code = f.read()
    with open(path_after, 'r', encoding='utf-8') as f:
        after_code = f.read()
    with open(path_gumtree, 'r', encoding='utf-8') as f:
        gumtree_data = json.load(f)
    actions = gumtree_data.get('actions', [])
    
    # Build AST queries for both versions of the code
    pre_patch_query = TreeQuery(before_code)
    post_patch_query = TreeQuery(after_code)

    results_per_action = []
    
    for action_data in actions:
        action = GumTreeAction(**action_data)
        try:
            action = GumTreeAction(**action_data)
            query = post_patch_query if action.action.startswith('insert') else pre_patch_query
            start, end = action.affected_range()
            search_end = end - 1 if end > start else start                
            affected_node = query.smallest_covering_ancestor(start, search_end)
            enclosing_scopes = find_enclosing_scopes(affected_node, path_before)
            results_per_action.append(enclosing_scopes)
        except Exception as e:
            print(f"Error processing action {action}: {e}")
    return results_per_action

def extract_fn_class_definitions(filepath: str) -> List[str]:
    """
    Parses a Python source code string and returns a list of all
    class and function definitions in the specified format.
    """

    with open(filepath, 'r', encoding='utf-8') as f:
        source_code = f.read()

    filepath = Path(filepath).parts[5:]
    filepath = Path(*filepath)
    parent_dir = filepath.parent
    filename = str(filepath.name)
    if filename.startswith("old_") or filename.startswith("new_"):
        filename = filename[4:]  

    filepath = Path(parent_dir, filename)  

    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        print(f"Error parsing {filepath}: {e}")
        return []

    visitor = CodeVisitor(filepath)
    visitor.visit(tree)
    return visitor.results

def format_scopes_to_string_typed_contextual(detailed_scopes: List[Tuple[str, str, str]]) -> List[str]:
    """
    Takes a nested list of scope tuples, creates unique, fully-typed 
    hierarchical contexts, and formats them into a single, sorted string.
    """
    all_context_strings = []

    for action_scopes in detailed_scopes:
        if not action_scopes:
            continue        
        context_parts = [f"{scope_type}:{scope_name}" for filename, scope_type, scope_name in action_scopes]
        # it is a guarantee that all action_scopes are from the same file, so the following is ok
        filepath = Path(action_scopes[0][0])
        filepath = filepath.parts[5:]
        filepath = Path(*filepath)
        context_string = str(filepath) + "::" + ".".join(context_parts)
        all_context_strings.append(context_string)

    unique_contexts = set(all_context_strings)
    return list(unique_contexts)

def filter_scopes_to_existing_or_ancestors(
    formatted_scopes: List[str], 
    existing_definitions: List[str]
) -> List[str]:
    """
    Filters a list of formatted scope strings to only include those that either:
    1. Already existed in the 'before' version (i.e., are in existing_definitions), or
    2. Have an ancestor (by progressively removing trailing segments) that existed.
    """
    filtered_contexts = set()

    for ctx in formatted_scopes:
        if ctx in existing_definitions:
            # Already existed before → keep as is
            filtered_contexts.add(ctx)
        else:
            # Try to find an existing ancestor
            parts = ctx.split("::", 1)  # Split only on first occurrence
            if len(parts) != 2:
                continue
            
            filename, hierarchy = parts
            segments = hierarchy.split(".")
            
            # Progressively strip trailing segments (deepest → higher)
            while len(segments) > 1:
                segments = segments[:-1]
                ancestor = filename + "::" + ".".join(segments)
                if ancestor in existing_definitions:
                    filtered_contexts.add(ancestor)
                    break
            # If no ancestor found, skip entirely (i.e., new top-level addition)
    
    return sorted(filtered_contexts)

def get_buggy_class_or_fn_names_with_context(record: dict, dataset_root: str) -> Dict[str, Any]:
    """
    Processes a single record from the dataset to find and format the
    names of all modified functions/classes.
    """
    all_detailed_scopes = []
    all_defs = []
    gumtree_files = record.get('gumtree_files', [])
    
    for rel_path_g in gumtree_files:
        rel_path_g = Path(dataset_root, rel_path_g)

        filename = rel_path_g.name
        rel_path_b = rel_path_g.parent / Path("old_" + filename.replace('.json', '.py'))
        rel_path_a = rel_path_g.parent / Path("new_" + filename.replace('.json', '.py'))
        
        detailed_scopes_for_file = identify_context(str(rel_path_b), str(rel_path_a), str(rel_path_g))       
        all_detailed_scopes.extend(detailed_scopes_for_file)

        defs = extract_fn_class_definitions(str(rel_path_b))
        all_defs.extend(defs)

    formatted_scopes = format_scopes_to_string_typed_contextual(all_detailed_scopes)    
    final_formatted_string = filter_scopes_to_existing_or_ancestors(formatted_scopes, all_defs)
    
    record['buggy_function_names'] = final_formatted_string
    
    return record