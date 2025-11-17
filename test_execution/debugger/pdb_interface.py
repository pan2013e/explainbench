import json
import ast
from pathlib import Path

from docker.models.containers import Container

from test_execution.util import REPRODUCER_LOC, read_from_container, write_to_container, apply_patch
from test_execution.debugger.python_parsing import get_matching_func_node, get_func_qualified_name
from test_execution.debugger.util import FunctionInfo, IOInfo

# The debugger operation script needs to be backward-compatible with earlier Python versions,
# making it slightly more complex than it would be in modern Python.
DEBUGGER_OPERATION_SCRIPT = r"""
import subprocess as sp
from subprocess import Popen
import json

def read_output(p):
    output = ""
    while not output.endswith("(Pdb) "):
        char = p.stdout.read(1).decode("utf-8")
        if not char:
            return True, output
        else:
            output += char
    return False, output.removesuffix("(Pdb) ").strip()

def get_pdb_response(p, prog_input):
    if not prog_input.endswith("\n"):
        prog_input += "\n"
    p.stdin.write(prog_input.encode("utf-8"))
    p.stdin.flush()

    return read_output(p)

def return_stack(p):
    def _get_stack_depth(stack):
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
p = sp.Popen(["/opt/miniconda3/envs/testbed/bin/python", "{test_loc}"], stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE)
read_output(p) # flush initial setup string
for idx in range({max_iter}):
    try:
        get_pdb_response(p, "import inspect")
    except BrokenPipeError:
        if idx == 0:
            while True:
                line = p.stderr.readline()
                if not line:
                    break
                print(line.decode()) # for debugging
            exit(0)
        else:
            raise
    _, param_values = get_pdb_response(p, PORTABLE_PARAMS_CMD)
    if "{func_name}".startswith("self."):
        _, self_value = get_pdb_response(p, "self")
        param_values += "\nself = " + self_value
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

class PDBManager():
    def __init__(self, container: Container, bug_info: dict, reproducer: str):
        self.container = container
        self.bug_info = bug_info
        self.reproducer = reproducer
    
    def _reset(self):
        self.container.exec_run("git reset --hard HEAD", workdir="/testbed")
        self.container.exec_run("git clean -df", workdir="/testbed")

    def _inject_breakpoint(self, target_func: FunctionInfo) -> ast.FunctionDef:
        """Returns modified function definition AST node."""
        file_content = read_from_container(
            self.container, target_func.file
        )
        ast_root = ast.parse(file_content)
        target_func_node = get_matching_func_node(ast_root, target_func)
        # Below: need to import pdb then set_trace; breakpoint() is not backward-compatible
        target_func_node.body.insert(0, ast.Import([ast.alias("pdb")]))
        target_func_node.body.insert(1, ast.Expr(ast.Call(ast.Attribute(ast.Name("pdb"), "set_trace"), [], [])))

        injected_file_content = ast.unparse(ast_root)
        write_to_container(
            self.container, 
            injected_file_content, 
            "/testbed" / Path(target_func.file)
        )
        return target_func_node
    
    def run_pdb_script(self, qual_func_name: str, max_iter: int = 10) -> str:
        pdb_script_loc = Path("/testbed/pdb_operator.py")
        debugger_op_script = DEBUGGER_OPERATION_SCRIPT.format(
            test_loc = REPRODUCER_LOC,
            func_name = qual_func_name,
            max_iter = max_iter,
        )
        write_to_container(self.container, debugger_op_script, pdb_script_loc)
        exec_result = self.container.exec_run(
            f"timeout 60s python {pdb_script_loc}", workdir="/testbed"
        )
        return exec_result.output.decode()

    def parse_script_output(self, proc_out: str) -> tuple[list[IOInfo], str]:
        presented_info: list[dict] = []
        # read output
        try:
            for line in proc_out.splitlines():
                presented_info.append(json.loads(line))
        except json.JSONDecodeError:
            return [], proc_out # exceptions in output
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
        return io_info, ""

    def get_func_io(self, target_func: FunctionInfo, use_fixed: bool = False, max_iter: int = 10) -> tuple[list[IOInfo], str]:
        self._reset()
        if use_fixed:
            apply_patch(self.container, self.bug_info["patch"])
        write_to_container(self.container, self.reproducer, Path(REPRODUCER_LOC))
        try:
            modified_func_node = self._inject_breakpoint(target_func)
        except AssertionError as e:
            if use_fixed:
                return [], str(e) # most likely function deletion
            else:
                raise # for buggy case, exception should be triggered as is
        qual_func_name = get_func_qualified_name(modified_func_node)
        script_output = self.run_pdb_script(qual_func_name, max_iter)
        func_io, error_str = self.parse_script_output(script_output)
        return func_io, error_str
    
    def exit(self):
        self.container.stop()
        self.container.remove()