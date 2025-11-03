import json
from dataclasses import dataclass
import io, tarfile
import ast
from pathlib import Path, PurePosixPath

from docker.models.containers import Container
from swebench.harness.docker_utils import copy_to_container
from tempfile import NamedTemporaryFile

from test_execution.test_runner import setup, inject_file

DEBUGGER_OPERATION_SCRIPT = r"""
import subprocess as sp
from subprocess import Popen
import json

def read_output(p: Popen[str]) -> tuple[bool, str]:
    output = ""
    while not output.endswith("(Pdb) "):
        char = p.stdout.read(1)
        if not char:
            return True, output
        else:
            output += char
    return False, output.removesuffix("(Pdb) ").strip()

def get_pdb_response(p: Popen[str], prog_input: str) -> tuple[bool, str]:
    if not prog_input.endswith("\n"):
        prog_input += "\n"
    p.stdin.write(prog_input)
    p.stdin.flush()

    return read_output(p)

p = sp.Popen(["/opt/miniconda3/envs/testbed/bin/python", "{test_loc}"], stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE, text=True)
read_output(p) # flush initial setup string

def return_stack(p: Popen[str]) -> None:
    def _get_stack_depth(stack: str) -> int:
        return stack.count("\n->")
    _, current_stack = get_pdb_response(p, "w")
    new_stack_depth = 0
    while new_stack_depth != _get_stack_depth(current_stack):
        get_pdb_response(p, "r")
        _, new_stack = get_pdb_response(p, "w")
        new_stack_depth = _get_stack_depth(new_stack)


MAX_NUM = 10
PORTABLE_PARAMS_CMD = "for param in inspect.signature({func_name}).parameters.values(): print(param.name, '=', locals()[param.name])"
for idx in range(MAX_NUM):
    get_pdb_response(p, "import inspect")
    _, param_values = get_pdb_response(p, PORTABLE_PARAMS_CMD)
    print(json.dumps({{
        "value_type": "parameter_values",
        "iteration_no": idx,
        "value_str": param_values
    }}))
    
    return_stack(p)
    _, return_value = get_pdb_response(p, '__return__')
    if return_value == "":
        return_value = "None"
    print(json.dumps({{
        "value_type": "return_value",
        "iteration_no": idx,
        "value_str": return_value
    }}))
    proc_end, _ = get_pdb_response(p, "c")
    if proc_end:
        break
"""

@dataclass
class FunctionInfo():
    file: str
    func_name: str

class AncestryVisitor(ast.NodeVisitor):
    def __init__(self):
        self.parent_stack = []
    
    def generic_visit(self, node):
        self.parent_stack.append(node)
        super().generic_visit(node)
        self.parent_stack.pop()
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        node.__setattr__("ancestor_types", [type(elem) for elem in self.parent_stack])

def get_buggy_methods(instance_id: str) -> list[FunctionInfo]:
    bugloc_infos = []
    with open("./dataset/extract_ground_truths/localization/ground_truth.jsonl") as f:
        for line in f:
            bugloc_infos.append(json.loads(line))
    raise NotImplementedError

def read_from_container(container: Container, pathname: str) -> str:
    abs_pathname = "/testbed/" + pathname
    stream, stat = container.get_archive(abs_pathname)

    file_like = io.BytesIO(b"".join(stream))
    with tarfile.open(fileobj=file_like) as tar:
        member = tar.getmembers()[0]
        file_content = tar.extractfile(member).read().decode("utf-8")
    return file_content

def inject_pdb_statement(container: Container, target_func: FunctionInfo) -> str:
    """Returns qualified function name."""
    file_content = read_from_container(
        container, target_func.file
    )
    ast_root = ast.parse(file_content)
    name_match_funcs = [
        node for node in ast.walk(ast_root)
        if (isinstance(node, ast.FunctionDef) and
            node.name == target_func.func_name)
    ]
    assert len(name_match_funcs) == 1, "Multiple functions matching name in file"
    target_func_node = name_match_funcs[0]
    target_func_node.body.insert(0, ast.Import([ast.alias("pdb")])) # import pdb
    target_func_node.body.insert(1, ast.Expr(ast.Call(ast.Attribute(ast.Name("pdb"), "set_trace"), [], [])))
    injected_file_content = ast.unparse(ast_root)
    with NamedTemporaryFile(
        buffering=0, prefix="instrumented-func-", suffix=".py"
    ) as f:
        f.write(injected_file_content.encode())
        copy_to_container(container, Path(f.name), "/testbed" / PurePosixPath(target_func.file))
    ast_root = AncestryVisitor().visit(ast_root)
    ancestor_types = target_func_node.__getattribute__("ancestor_types")
    qual_func_name = ("self." if (ast.ClassDef) in ancestor_types else "") + target_func.func_name
    return qual_func_name

def get_test(instance_id: str) -> str:
    with open("dataset/context/intent_pbtassertion.json") as f:
        all_test_info = json.load(f)
    target_test_info = [t_info for t_info in all_test_info if t_info["instance_id"] == instance_id]
    return target_test_info[0]["test"]

if __name__ == '__main__':
    DEBUG=True
    MY_INSTANCE_ID = "sympy__sympy-13551"
    my_funcinfo = FunctionInfo(file="sympy/concrete/products.py", func_name="_eval_product")
    my_container, _ = setup(MY_INSTANCE_ID)
    try:
        my_test = get_test(MY_INSTANCE_ID)
        qual_func_name = inject_pdb_statement(my_container, my_funcinfo)
        reproducer_loc = "/testbed/reproducer.py"
        inject_file(my_container, my_test, reproducer_loc)
        debugger_op_script = DEBUGGER_OPERATION_SCRIPT.format(
            test_loc = reproducer_loc,
            func_name = qual_func_name,
        )
        inject_file(my_container, debugger_op_script, "/testbed/pdb_operator.py")
        exec_result = my_container.exec_run("python pdb_operator.py", workdir="/testbed")
        with open(f"debugger_output/{MY_INSTANCE_ID}.txt", "w") as f:
            print(exec_result.output.decode().strip(), file=f)
    except:
        raise
    finally:
        if not DEBUG:
            my_container.stop()
            my_container.remove()
        else:
            pass
        
    