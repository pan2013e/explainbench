import os
import ast
import sys
import threading

class ThreadSafeCache:
    def __init__(self, max_size):
        self._cache = {}
        self._lock = threading.Lock()
        self._max_size = max_size
    
    def get_or_set(self, key, factory):
        with self._lock:
            if key not in self._cache:
                if len(self._cache) >= self._max_size:
                    self._cache.clear()
                self._cache[key] = factory()
            return self._cache[key]

# Adopted from https://github.com/alexmojaki/executing/blob/master/executing/executing.py
class QualnameVisitor(ast.NodeVisitor):
    def __init__(self):
        super(QualnameVisitor, self).__init__()
        self.stack = []
        self.qualnames = {}

    def add_qualname(self, node, name=None):
        name = name or node.name
        self.stack.append(name)
        if getattr(node, 'decorator_list', ()):
            lineno = node.decorator_list[0].lineno
        else:
            lineno = node.lineno
        self.qualnames.setdefault((name, lineno), ".".join(self.stack))

    def visit_FunctionDef(self, node, name=None):
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)), node
        self.add_qualname(node, name)
        self.stack.append('<locals>')
        children = []
        if isinstance(node, ast.Lambda):
            children = [node.body]
        else:
            children = node.body
        for child in children:
            self.visit(child)
        self.stack.pop()
        self.stack.pop()

        for field, child in ast.iter_fields(node):
            if field == 'body':
                continue
            if isinstance(child, ast.AST):
                self.visit(child)
            elif isinstance(child, list):
                for grandchild in child:
                    if isinstance(grandchild, ast.AST):
                        self.visit(grandchild)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        assert isinstance(node, ast.Lambda)
        self.visit_FunctionDef(node, '<lambda>')

    def visit_ClassDef(self, node):
        assert isinstance(node, ast.ClassDef)
        self.add_qualname(node)
        self.generic_visit(node)
        self.stack.pop()

QUALNAME_CACHE = ThreadSafeCache(max_size=131072)

def get_func_qualname(frame, source_lines_cache={}):
    if sys.version_info >= (3, 11):
        return frame.f_code.co_qualname
    if not os.path.exists(frame.f_code.co_filename):
        return frame.f_code.co_name
    key1 = frame.f_code.co_filename
    key2 = (frame.f_code.co_name, frame.f_code.co_firstlineno)
    qualnames = QUALNAME_CACHE.get_or_set(key1, lambda: _update_func_qualnames(key1, source_lines_cache))
    return qualnames.get(key2, frame.f_code.co_name)

def _update_func_qualnames(filename, source_lines_cache):
    visitor = QualnameVisitor()
    if filename not in source_lines_cache:
        with open(filename, 'r', encoding='utf-8') as f:
            source_lines_cache[filename] = f.readlines()
    source = ''.join(source_lines_cache[filename])
    tree = ast.parse(source, filename=filename)
    visitor.visit(tree)
    return visitor.qualnames
