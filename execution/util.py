import json
import tarfile
import tempfile
import libcst as cst

from io import BytesIO
from collections import defaultdict
from pathlib import PurePosixPath, Path
from datasets import load_dataset
from docker.models.containers import Container
from swebench.harness.docker_utils import (
    copy_to_container,
    exec_run_with_timeout
)

def read_from_docker(container: Container, path: PurePosixPath) -> str:
    """Read a file from inside a Docker container."""
    tar_stream, _ = container.get_archive(str(path))
    file_content = b""
    for chunk in tar_stream:
        file_content += chunk
    with tarfile.open(fileobj=BytesIO(file_content)) as tar:
        member = tar.getmembers()[0]
        file = tar.extractfile(member)
        return file.read().decode('utf-8')

def copy_directory_from_docker(container: Container, src_path: PurePosixPath, dst_path: Path):
    tar_stream, _ = container.get_archive(str(src_path))
    file_content = b""
    for chunk in tar_stream:
        file_content += chunk
    with tarfile.open(fileobj=BytesIO(file_content)) as tar:
        tar.extractall(path=dst_path)

def write_to_docker(container: Container, path: str, content: str, perm: str = None):
    with tempfile.NamedTemporaryFile("w") as f:
        f.write(content)
        f.flush()
        copy_to_container(container, Path(f.name), Path(path))
    if perm:
        exec_run_with_timeout(container, f"chmod {perm} {path}")

class Injector(cst.CSTTransformer):
    def __init__(self, target_funcs, deco_arg=""):
        self.targets = set(target_funcs)
        self.deco_arg = deco_arg

    def leave_FunctionDef(self, original_node, updated_node):
        if original_node.name.value not in self.targets:
            return updated_node
        existing_decos = list(updated_node.decorators or [])
        new_deco = cst.Decorator(
            decorator=cst.Call(
                func=cst.Name("trace"),
                args=[cst.Arg(value=cst.SimpleString(f'"{self.deco_arg}"'))]
            )
        )
        existing_decos.append(new_deco)
        return updated_node.with_changes(decorators=existing_decos)

class TestCodeInjector:
    def __init__(self, container: Container, instance_id: str):
        self.dataset = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
        self.container = container
        self.instance_id = instance_id

    def __call__(self, prefix: str):
        if 'astropy' in self.instance_id:
            return self._astropy(prefix)
        elif 'sympy' in self.instance_id:
            return self._sympy(prefix)
        else:
            raise NotImplementedError()
    
    def _get_test_names(self) -> list[str]:
        instance = self.dataset.filter(lambda x: x["instance_id"] == self.instance_id)
        assert len(instance) == 1, f"Instance {self.instance_id} not found"
        instance = instance[0]
        return json.loads(instance['FAIL_TO_PASS']) + json.loads(instance['PASS_TO_PASS'])
    
    def _inject_file(self, file: str, funcs: list[str], prefix: str):
        code = read_from_docker(self.container, PurePosixPath(file))
        code = 'from tracer import trace\n' + code
        tree = cst.parse_module(code)
        transformer = Injector(funcs, prefix)
        tree = tree.visit(transformer)
        code = tree.code
        write_to_docker(self.container, PurePosixPath(file), code)

    def _astropy(self, prefix: str):
        test_funcs = self._get_test_names()
        cleaned = []
        for func in test_funcs:
            if '[' in func:
                func = func[:func.index('[')]
            cleaned.append(func)
        test_funcs = list(set((func.split('::')[0], func.split('::')[1]) for func in cleaned))
        test_funcs_dict = defaultdict(list)
        for file, func in test_funcs:
            test_funcs_dict[file].append(func)
        for file, funcs in test_funcs_dict.items():
            self._inject_file(file, funcs, prefix)
    
    def _sympy(self, prefix: str):
        test_funcs = self._get_test_names()
        self._inject_file('sympy/core/tests/test_basic.py', test_funcs, prefix)
    