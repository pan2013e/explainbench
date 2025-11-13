import ast

from test_execution.debugger.util import FunctionInfo

class AncestryVisitor(ast.NodeVisitor):
    INNERMOST_CLASS="included_class"

    def __init__(self):
        self.parent_stack = []
    
    def generic_visit(self, node):
        self.parent_stack.append(node)
        super().generic_visit(node)
        self.parent_stack.pop()
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        class_ancestry = [
            elem.name for elem in self.parent_stack
            if isinstance(elem, ast.ClassDef)
        ]
        class_name = None if len(class_ancestry) == 0 else class_ancestry[-1]
        node.__setattr__(AncestryVisitor.INNERMOST_CLASS, class_name)
        self.generic_visit(node)

def get_matching_func_node(ast_root: ast.AST, target_func: FunctionInfo) -> ast.FunctionDef:
    name_match_funcs = [
        node for node in ast.walk(ast_root)
        if (isinstance(node, ast.FunctionDef) and
            node.name == target_func.func_name)
    ]
    AncestryVisitor().visit(ast_root)
    if target_func.class_name != "":
        name_match_funcs = [
            node for node in name_match_funcs
            if node.__getattribute__(AncestryVisitor.INNERMOST_CLASS) == target_func.class_name
        ]
    assert len(name_match_funcs) == 1, f"Multiple functions matching {target_func} in file: {name_match_funcs}"
    return name_match_funcs[0]

def get_func_qualified_name(func_def_node: ast.FunctionDef) -> str:
    assert hasattr(func_def_node, AncestryVisitor.INNERMOST_CLASS)
    class_name = func_def_node.__getattribute__(AncestryVisitor.INNERMOST_CLASS)
    arg_names = [arg.arg for arg in func_def_node.args.args]
    decorator_names = [
        decorator.id for decorator in func_def_node.decorator_list
        if isinstance(decorator, ast.Name)
    ]
    qualifier = ""
    # if not target_func.containing_funcs:
    if len(arg_names) > 0 and arg_names[0] == "self":
        qualifier = "self."
    elif len(arg_names) > 0 and arg_names[0] == "cls" and "classmethod" in decorator_names:
        qualifier = "cls."
    elif class_name is not None and "staticmethod" in decorator_names:
        qualifier = class_name + "."
    qual_func_name = qualifier + func_def_node.name
    return qual_func_name