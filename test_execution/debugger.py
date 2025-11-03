import json
from dataclasses import dataclass
import io, tarfile
import ast
import re
from pathlib import Path, PurePosixPath

from docker.models.containers import Container
from swebench.harness.docker_utils import copy_to_container
from tempfile import NamedTemporaryFile

from test_execution.test_runner import setup, inject_file, apply_patch

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

def return_stack(p: Popen[str]) -> None:
    def _get_stack_depth(stack: str) -> int:
        return stack.count("\n->")
    _, current_stack = get_pdb_response(p, "w")
    new_stack_depth = 999
    has_return_value = False
    while not ((new_stack_depth == _get_stack_depth(current_stack)) and has_return_value):
        assert new_stack_depth >= _get_stack_depth(current_stack), new_stack
        get_pdb_response(p, "r")
        _, new_stack = get_pdb_response(p, "w")
        new_stack_depth = _get_stack_depth(new_stack)
        has_return_value = ")->" in new_stack

PORTABLE_PARAMS_CMD = "for param in inspect.signature({func_name}).parameters.values(): print(param.name, '=', locals()[param.name])"
p = sp.Popen(["/opt/miniconda3/envs/testbed/bin/python", "{test_loc}"], stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE, text=True)
read_output(p) # flush initial setup string
for idx in range({max_iter}):
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

@dataclass
class IOInfo():
    input_values: str
    output_value: str

    def to_dict(self) -> dict[str, str]:
        return {
            "input_values": self.input_values,
            "output_value": self.output_value,
        }

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
    bugloc_infos: list[dict] = []
    with open("./dataset/extract_ground_truths/localization/ground_truth_w_fullname.jsonl") as f:
        for line in f:
            bugloc_infos.append(json.loads(line))
    target_bugloc_info = [info for info in bugloc_infos 
                          if info["instance_id"] == instance_id]
    assert len(target_bugloc_info) == 1, f"Target bug locations non-singular: {target_bugloc_info}"
    buggy_methods = []
    for buggy_func_full_name in target_bugloc_info[0]["buggy_function_names"]:
        m = re.match(rf"{instance_id}/(.+)::.*function:(.+)", buggy_func_full_name)
        assert m is not None, buggy_func_full_name
        buggy_methods.append(FunctionInfo(
            file=m.group(1),
            func_name=m.group(2)
        ))
    return buggy_methods

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

def get_function_io(
    instance_id: str,
    func_info: FunctionInfo,
    from_fixed: bool = False,
    max_iter: int = 10,
    debug: bool = False
) -> list[IOInfo]:
    def _parse_script_output(proc_out: str) -> list[IOInfo]:
        presented_info: list[dict] = []
        # read output
        try:
            for line in proc_out.splitlines():
                presented_info.append(json.loads(line))
        except json.JSONDecodeError:
            return [] # exceptions in output
        # parse to IOInfo
        assert len(presented_info) % 2 == 0
        io_info: list[IOInfo] = []
        for input_info, output_info in zip(presented_info[::2], presented_info[1::2]):
            assert input_info["value_type"] == "parameter_values"
            assert output_info["value_type"] == "return_value"
            assert input_info["iteration_no"] == output_info["iteration_no"]
            io_info.append(IOInfo(
                input_values = input_info["value_str"],
                output_value = output_info["value_str"],
            ))
        return io_info
    
    def _run_pdb_script(container: Container, setup_info: dict) -> str:
        if from_fixed:
            apply_patch(container, setup_info["patch"])
        my_test = get_test(instance_id)
        qual_func_name = inject_pdb_statement(container, func_info)
        reproducer_loc = "/testbed/reproducer.py"
        inject_file(container, my_test, reproducer_loc)
        debugger_op_script = DEBUGGER_OPERATION_SCRIPT.format(
            test_loc = reproducer_loc,
            func_name = qual_func_name,
            max_iter = max_iter,
        )
        pdb_script_loc = "/testbed/pdb_operator.py"
        inject_file(container, debugger_op_script, pdb_script_loc)
        exec_result = container.exec_run(f"python {pdb_script_loc}", workdir="/testbed")
        return exec_result.output.decode()

    container, setup_info = setup(instance_id)
    try:
        exec_output = _run_pdb_script(container, setup_info)
        return _parse_script_output(exec_output)
    finally:
        if not debug:
            container.stop()
            container.remove()

def main(instance_id: str, save_dir: Path, max_iter: int = 10, debug: bool = False):
    save_bug_dir = save_dir / instance_id
    save_bug_dir.mkdir(exist_ok = True)

    buggy_funcs = get_buggy_methods(instance_id)
    for buggy_func in buggy_funcs:
        buggy_io = get_function_io(
            instance_id = instance_id,
            func_info = buggy_func,
            max_iter = max_iter,
            debug = debug
        )
        fixed_io = get_function_io(
            instance_id = instance_id,
            func_info = buggy_func,
            from_fixed = True,
            max_iter = max_iter,
            debug = debug
        )
        func_full_name = buggy_func.file.removesuffix(".py").replace("/", ".") + "." + buggy_func.func_name
        save_file = save_bug_dir / (func_full_name + ".json")
        save_file.write_text(json.dumps({
            "buggy_io": [info.to_dict() for info in buggy_io],
            "fixed_io": [info.to_dict() for info in fixed_io],
        }, indent=2))


if __name__ == '__main__':
    DEBUG=False
    MY_INSTANCE_ID = "sympy__sympy-14531"
    
    main(MY_INSTANCE_ID, Path("./debugger_output/"))
    