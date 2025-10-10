import re
import ast
import asttokens

from pydantic import BaseModel
from typing import Callable, Optional, Literal, Tuple, List

class GumTreeAction(BaseModel):
    action: Literal['insert-node', 'insert-tree', 'delete-node', 'delete-tree', 'move-tree', 'update-node']
    tree: str
    parent: Optional[str] = None
    at: Optional[int] = None
    label: Optional[str] = None

    @staticmethod
    def _parse_range(gt_string: str) -> Optional[Tuple[int, int]]:
        m = re.compile(r'.*?\[(\d+),(\d+)\]').match(gt_string)
        if not m: return None
        return int(m.group(1)), int(m.group(2))

    def affected_range(self) -> Tuple[int, int]:
        res = self._parse_range(self.tree)
        if res is None: raise ValueError(f"Could not parse range from tree string: {self.tree}")
        return res    

class Parentage(ast.NodeTransformer):
    parent = None

    def visit(self, node: ast.AST):
        node.parent = self.parent
        self.parent = node
        node = super().visit(node)
        if isinstance(node, ast.AST):
            self.parent = node.parent
        return node

class TreeQuery:
    def __init__(self, code):
        self.code = code
        parsed_tree = ast.parse(code)    
        tree_with_parents = Parentage().visit(parsed_tree)
        self.atok = asttokens.ASTTokens(code, tree=tree_with_parents)
    
    def offset_to_line(self, offset: int):
        return self.atok._line_numbers.offset_to_line(offset)
    
    def character_offsets(self, node: ast.AST):
        return self.atok.get_text_range(node)
    
    def line_col_offsets(self, node: ast.AST):
        return self.atok.get_text_positions(node, padded=True)
    
    def children_in_order(self, node: ast.AST, ordering: Callable[[ast.AST], int]=id):
        '''Get children of a node in source code order, breaking ties with the given ordering function.'''
        kids = list(ast.iter_child_nodes(node))
        kids.sort(key=lambda n: (*self.atok.get_text_range(n), ordering(n)))
        return kids

    def smallest_covering_ancestor(self, L: int, R: int=None) -> ast.AST:
        '''Find the smallest ancestor node whose span fully covers [L, R].'''
        if R is None:
            R = L
        assert L <= R, f"Invalid range: [{L}, {R}]"
        root = self.atok.tree
        rs, re = self.atok.get_text_range(root)
        assert rs <= L and R <= re, f"Out of bounds: [{L}, {R}] not in [{rs}, {re}]"
        cur = root
        changed = True
        while changed:
            changed = False
            for child in self.children_in_order(cur):
                cs, ce = self.atok.get_text_range(child)
                if cs <= L and R <= ce:
                    cur = child
                    changed = True
                    break
        return cur

def find_enclosing_scopes(node: ast.AST, filename: str) -> List[Tuple[str, str, str]]:
    """
    Traces the ancestry of an AST node and collects the filename, types, and names
    of all enclosing functions and classes.
    """
    scopes = []
    current_node = node
    filename = filename.replace("old_", "").strip()
    while current_node:
        if isinstance(current_node, ast.FunctionDef):
            scopes.append((filename, 'function', current_node.name))
        elif isinstance(current_node, ast.ClassDef):
            scopes.append((filename, 'class', current_node.name))
        current_node = getattr(current_node, 'parent', None)
    scopes.reverse()
    return scopes