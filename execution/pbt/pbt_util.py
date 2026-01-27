import ast


class RemoveMainGuard(ast.NodeTransformer):
    def visit_If(self, node: ast.If):
        # Match: if __name__ == "__main__":
        if (
            isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "__main__"
        ):
            # Drop the entire if-statement
            return None

        return self.generic_visit(node)


class GetHypothesisTests(ast.NodeVisitor):
    def __init__(self):
        self.test_functions = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "given"
            ):
                self.test_functions.append(node)
        self.generic_visit(node)


def add_hypothesis_calls(source: str) -> str:
    tree = ast.parse(source)
    getter = GetHypothesisTests()
    getter.visit(tree)

    for test_func in getter.test_functions:
        call_expr = ast.Expr(
            value=ast.Call(
                func=ast.Name(id=test_func.name),
                args=[],
                keywords=[]
            )
        )
        tree.body.append(call_expr)

    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def strip_main_guard(source: str) -> str:
    tree = ast.parse(source)
    tree = RemoveMainGuard().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)
