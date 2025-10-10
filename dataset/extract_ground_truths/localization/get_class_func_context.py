import ast
import json
from typing import List, Tuple

from extract_ground_truths.diff_analyzer import TreeQuery, find_enclosing_scopes, GumTreeAction

def identify_context(path_before: str, path_after: str, path_gumtree: str) -> Set[Tuple[str, str]]:
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

    # Identify all functions/classes that existed in the original file.
    original_scopes = set()
    for node in ast.walk(pre_patch_query.atok.tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            scope_type = 'function' if isinstance(node, ast.FunctionDef) else 'class'
            original_scopes.add((scope_type, node.name))
    
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
            
            # if the first try fails, try to use the parent
            if not enclosing_scopes and action.action.startswith('insert') and action.parent:
                parent_range = GumTreeAction._parse_range(action.parent)
                if parent_range:
                    p_start, p_end = parent_range
                    parent_node = query.smallest_covering_ancestor(p_start, p_end - 1 if p_end > p_start else p_start)
                    enclosing_scopes = find_enclosing_scopes(parent_node, path_before)

            results_per_action.append(enclosing_scopes)
        except Exception as e:
            print(f"Error processing action {action}: {e}")

    return results_per_action

def format_scopes_to_string_typed_contextual(detailed_scopes: List[List[Tuple[str, str]]]) -> str:
    """
    Takes a nested list of scope tuples, creates unique, fully-typed 
    hierarchical contexts, and formats them into a single, sorted string.
    """
    all_context_strings = []

    for action_scopes in detailed_scopes:
        if not action_scopes:
            continue        
        context_parts = [f"{scope_type}:{scope_name}" for scope_type, scope_name in action_scopes]  
        all_context_strings.append(".".join(context_parts))

    unique_contexts = set(all_context_strings)
    return ", ".join(sorted(list(unique_contexts)))