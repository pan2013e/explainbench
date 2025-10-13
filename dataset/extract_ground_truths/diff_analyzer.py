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
        m = re.compile(r'.*?\[(\d+),(\d+)\]', flags=re.DOTALL).match(gt_string)
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
        '''Convert a character offset to `(line, column)`. Lines and columns are 1-indexed.'''
        return self.atok._line_numbers.offset_to_line(offset)
    
    def character_offsets(self, node: ast.AST):
        '''Get the `(start, end)` character offsets of a node.'''
        return self.atok.get_text_range(node)
    
    def line_col_offsets(self, node: ast.AST):
        '''Get the `((start_line, start_col), (end_line, end_col))` of a node. Lines and columns are 1-indexed.'''
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

class CodeVisitor(ast.NodeVisitor):
    """
    An AST visitor that traverses the code tree to find all class and
    function definitions.
    """
    def __init__(self, filename: str):
        self.filename = filename
        self.results: List[str] = []
        self.path: List[Tuple[str, str]] = []

    def _process_node(self, node: ast.AST, node_type: str):
        """
        Handler for both FunctionDef, AsyncFunctionDef, and ClassDef nodes.
        """
        self.path.append((node_type, node.name))

        # path = [('class', 'Table'), ('function', '_convert')]
        # becomes "class:Table.function:_convert"
        path_segments = [f"{t}:{n}" for t, n in self.path]
        structured_path = ".".join(path_segments)

        self.results.append(f"{self.filename}::{structured_path}")

        # Continue traversing into the children of this node to find nested items.
        self.generic_visit(node)

        # After visiting children, pop from the path to return to the parent scope.
        self.path.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Called when a standard 'def' is found."""
        self._process_node(node, 'function')

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Called when an 'async def' is found."""
        self._process_node(node, 'function')

    def visit_ClassDef(self, node: ast.ClassDef):
        """Called when a 'class' is found."""
        self._process_node(node, 'class')