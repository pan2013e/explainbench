import os
import ast
import uuid
import tarfile
import tempfile
import docker

from io import BytesIO
from pathlib import Path, PurePosixPath
from docker.client import DockerClient
from docker.models.containers import Container
from swebench.harness.run_evaluation import GIT_APPLY_CMDS
from swebench.harness.docker_utils import cleanup_container, copy_to_container

from execution.util import get_test_patch

__all__ = [
    'get_function_code',
]

class FunctionVisitor(ast.NodeVisitor):
    def __init__(self, fn_name: str):
        self.fn_name = fn_name
        self.candidates = []
        self.stack = []
        
    def _qualified_name(self):
        return '.'.join(self.stack)
    
    def _node_span(self, node):
        start = getattr(node, 'lineno', None)
        end = getattr(node, 'end_lineno', None)
        return start, end
    
    def visit_ClassDef(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()
    
    def visit_FunctionDef(self, node):
        self.stack.append(node.name)
        qname = self._qualified_name()
        start, end = self._node_span(node)
        if qname == self.fn_name or node.name == self.fn_name:
            self.candidates.append((node, qname, start, end))
        self.generic_visit(node)
        self.stack.pop()
    
    def visit_AsyncFunctionDef(self, node):
        self.stack.append(node.name)
        qname = self._qualified_name()
        start, end = self._node_span(node)
        if qname == self.fn_name or node.name == self.fn_name:
            self.candidates.append((node, qname, start, end))
        self.generic_visit(node)
        self.stack.pop()

class DocRemover(ast.NodeTransformer):
    def _remove_docstring_if_present(self, node):
        if (node.body and
                isinstance(node.body[0], ast.Expr) and
                isinstance(node.body[0].value, ast.Constant) and
                isinstance(node.body[0].value.value, str)):
            node.body.pop(0)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        return self._remove_docstring_if_present(node)

    def visit_AsyncFunctionDef(self, node):
        return self._remove_docstring_if_present(node)

def get_image_name(instance_id: str):
    new_id = instance_id.replace('__', '_1776_')
    return f'swebench/sweb.eval.x86_64.{new_id}'

def test_image_exists(client: DockerClient, image_name: str):
    try:
        client.images.get(image_name)
    except docker.errors.ImageNotFound:
        client.images.pull(image_name) 

def start_docker_container(instance_id: str):
    client = docker.from_env()
    image_name = get_image_name(instance_id)
    test_image_exists(client, image_name)
    container = None
    try:
        container = client.containers.create(
            image=image_name,
            name=f'sweb.eval.{instance_id}.effect_ground_truth.{uuid.uuid4()}',
            user='root',
            detach=True,
            command="tail -f /dev/null",
            platform='linux/x86_64'
        )
        container.start()
    except Exception as e:
        cleanup_container(client, container, None)
        raise e
    return container

def apply_patch(container: Container, patch: str):
    with tempfile.NamedTemporaryFile('w') as f:
        f.write(patch)
        f.flush()
        copy_to_container(container, Path(f.name), PurePosixPath('/tmp/patch.diff'))
    applied_patch = False
    for cmd in GIT_APPLY_CMDS:
        result = container.exec_run(
            f'{cmd} /tmp/patch.diff',
            workdir='/testbed',
            user='root',
        )
        if result.exit_code == 0:
            applied_patch = True
            break
        else:
            print(f'Attempt to apply patch with "{cmd}" failed: {result.output.decode("utf-8")}')
    container.exec_run('rm -f /tmp/patch.diff', user='root')
    if not applied_patch:
        raise ValueError('Failed to apply patch inside container')

def read_from_container(container: Container, file_path: str):
    tar_stream, _ = container.get_archive(file_path)
    file_content = b""
    for chunk in tar_stream:
        file_content += chunk
    with tarfile.open(fileobj=BytesIO(file_content)) as tar:
        member = tar.getmembers()[0]
        f = tar.extractfile(member)
        assert f, "Failed to extract file from tar archive"
        return f.read().decode('utf-8')

def remove_docstrings(source: str) -> str:
    try:
        tree = ast.parse(source)
        transformer = DocRemover()
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        return ast.unparse(new_tree)
    except (SyntaxError, ValueError) as e:
        print(f"Failed to remove docstrings, falling back to original source: {e}")
        return source

def get_func_code_impl(code: str, fn_name: str, line_hint: int = None):
    tree = ast.parse(code)
    visitor = FunctionVisitor(fn_name)
    visitor.visit(tree)
    if not visitor.candidates:
        raise ValueError(f'Cannot find function {fn_name}')
    chosen = None
    if line_hint:
        for node, _, start, end in visitor.candidates:
            if start and end and start <= line_hint <= end:
                chosen = node
                break
    if not chosen:
        chosen = visitor.candidates[0][0]
    return ast.unparse(chosen)

def get_function_code(instance_id: str, file_path: str, fn_name: str, 
                      *, patch: str = None, line_hint: tuple[int, int] = None, remove_doc=False):
    assert os.path.isabs(file_path), "file_path must be absolute"
    if line_hint:
        pre_hint, post_hint = line_hint
    else:
        pre_hint = post_hint = None
    container = start_docker_container(instance_id)
    test_patch = get_test_patch(instance_id)
    try:
        if test_patch: apply_patch(container, test_patch)
    finally: pass
    try:
        pre_file = read_from_container(container, file_path)
        try:
            if patch: apply_patch(container, patch)
        finally: pass
        post_file = read_from_container(container, file_path)
    finally:
        cleanup_container(container.client, container, 'quiet')
    pre_code = get_func_code_impl(pre_file, fn_name, pre_hint)
    post_code = get_func_code_impl(post_file, fn_name, post_hint)
    if remove_doc:
        pre_code = remove_docstrings(pre_code)
        post_code = remove_docstrings(post_code)
    return pre_code, post_code

if __name__ == "__main__":
    instance_id = "astropy__astropy-12907"
    file_path = "/testbed/astropy/modeling/separable.py"
    fn_name = "_cstack"
    patch = '''diff --git a/astropy/modeling/separable.py b/astropy/modeling/separable.py
--- a/astropy/modeling/separable.py
+++ b/astropy/modeling/separable.py
@@ -242,7 +242,7 @@ def _cstack(left, right):
         cright = _coord_matrix(right, 'right', noutp)
     else:
         cright = np.zeros((noutp, right.shape[1]))
-        cright[-right.shape[0]:, -right.shape[1]:] = 1
+        cright[-right.shape[0]:, -right.shape[1]:] = right
 
     return np.hstack([cleft, cright])
 
'''
    pre_code, post_code = get_function_code(instance_id, file_path, fn_name, remove_doc=True, patch=patch)
    print(pre_code)
    print(post_code)