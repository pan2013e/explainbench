import re
import ast
import asttokens

from pydantic import BaseModel
from typing import Callable, Optional, Literal

class GumTreeAction(BaseModel):
    action: Literal['insert-node', 'insert-tree', 'delete-node', 'delete-tree', 'move-tree', 'update-node']
    tree: str
    parent: Optional[str] = None
    at: Optional[int] = None
    label: Optional[str] = None

    def affected_range(self):
        pattern = re.compile(r'.*?\[(\d+),(\d+)\]')
        m = pattern.match(self.tree)
        assert m
        return int(m.group(1)), int(m.group(2))

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
        self.atok = asttokens.ASTTokens(code, parse=True)
        assert self.atok.tree is not None, "Failed to parse code"
        self.atok._tree = Parentage().visit(self.atok.tree)
    
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
