import sys
import os
import ast
import io, tokenize
import inspect

from functools import lru_cache
from collections import defaultdict
from pathlib import Path
from tracer.util import get_func_qualname
from tracer.serializer import serialize, dump

__all__ = ['ExecutionTracer', 'Tracker']

@lru_cache(maxsize=8192)
def _should_ignore(filename, *whitelist):
    """Check if the call is from a standard library or test framework"""
    if not filename:
        return False

    # Check for built-in modules
    if filename.startswith('<frozen'):
        return True

    # Exclude tracer's plugin module
    if 'tracer_plugin' in filename:
        return True
    
    # Normalize the path
    normalized_path = os.path.normpath(filename)
    path_parts = normalized_path.split(os.sep)
    
    if any(part in whitelist for part in path_parts):
        return False

    # Exclude calls to third-party libraries
    if 'site-packages' in normalized_path:
        return True
    
    # Check if it's in the standard Python installation
    python_paths = [
        'lib/python',
        'Lib\\',
        '/usr/lib/python',
        '/usr/local/lib/python'
    ]
    
    if any(py_path in normalized_path for py_path in python_paths):
        if any(part in whitelist for part in path_parts):
            return False
        return True
    
    return False

def _strip_comments_preserving_strings(line):
    """
    Remove inline comments from a single source line while preserving
    '#' inside string literals. Uses tokenize to avoid breaking strings.
    Returns a best-effort comment-free source line.
    """
    try:
        tokens = []
        for tok in tokenize.generate_tokens(io.StringIO(line).readline):
            if tok.type == tokenize.COMMENT:
                continue
            tokens.append((tok.type, tok.string))
        return tokenize.untokenize(tokens)
    except Exception:
        return line.split('#', 1)[0]

@lru_cache(maxsize=65536)
def _get_vars_defined_and_used(source_line):
    """Return separate lists of variables defined and used in the statement."""
    defined, used = set(), set()
    if not source_line or not source_line.strip():
        return [], []

    code_no_comments = _strip_comments_preserving_strings(source_line).rstrip()
    stripped = code_no_comments.strip()
    if not stripped:
        return [], []

    code_to_parse = stripped
    # If the logical code (without comments) ends with a colon, make it parseable
    if stripped.endswith(':'):
        code_to_parse += "\n    pass"

    try:
        tree = ast.parse(code_to_parse, mode="exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    defined.add(node.id)
                elif isinstance(node.ctx, ast.Load):
                    used.add(node.id)
    except SyntaxError:
        # best-effort only
        pass

    return list(defined), list(used)

class ExecutionTracer:
    def __init__(
        self,
        output_file="trace.jsonl",
        include_stdlib=None,
        allowed_functions=None,
    ):
        self.call_stack = []
        self.call_graph = defaultdict(set)
        self.call_counts = defaultdict(int)
        self.max_depth = 0
        self.trace_data = []
        self.output_file = output_file
        self.source_cache = {} 
        self.event_id = 0
        self.control_stack = []
        self.inherited_control_stack = []
        self.control_stack_stack = []     
        self.last_def_event = defaultdict(dict)
        self.function_variables_stack = []
        self.include_stdlib = list(include_stdlib) if include_stdlib else []
        self.allowed_functions = list(allowed_functions) if allowed_functions else []
        
    def __enter__(self):
        self.start_tracing()
        return self
    
    def __exit__(self, exc_type, exc_value, tb):
        self.stop_tracing()
        try:
            self.save_trace()
        except Exception as e:
            print("Failed to save trace to {}: {}".format(self.output_file, e), file=sys.stderr, flush=True)
        return False

    def _is_function_allowed(self, frame):
        """
        Return True if this function should be traced, according to
        the functions file (if any). If no functions file is configured,
        trace everything (return True).
        """
        # No whitelist => trace everything
        if not self.allowed_functions:
            return True

        # We have a whitelist; check against qualified_name
        func_info = self._get_function_info(frame)
        return func_info["qualified_name"] in self.allowed_functions

    def _get_source_line(self, filename, line_no):
        """Get the source code line from a file"""
        try:
            if filename not in self.source_cache:
                with open(filename, 'r', encoding='utf-8') as f:
                    self.source_cache[filename] = f.readlines()
            
            if 1 <= line_no <= len(self.source_cache[filename]):
                return self.source_cache[filename][line_no - 1].rstrip()
            return ""
        except (IOError, OSError, UnicodeDecodeError):
            return ""

    def _get_function_parameters(self, frame):
        """Extract function parameters and their values"""
        code = frame.f_code
        func_name = code.co_name
        param_names = code.co_varnames[:code.co_argcount]
        params = {}
        
        for name in param_names:
            if func_name == '__init__' and name == 'self':
                continue
            if name in frame.f_locals:
                self.stop_tracing()
                params[name] = serialize(frame.f_locals[name])
                self.start_tracing()
        
        # Handle *args and **kwargs
        if code.co_flags & 0x04: 
            varargs_name = code.co_varnames[code.co_argcount]
            if varargs_name in frame.f_locals:
                self.stop_tracing()
                params['*' + varargs_name] = serialize(frame.f_locals[varargs_name])
                self.start_tracing()
                
        if code.co_flags & 0x08: 
            kwargs_index = code.co_argcount
            if code.co_flags & 0x04:  # also has *args
                kwargs_index += 1
            kwargs_name = code.co_varnames[kwargs_index]
            if kwargs_name in frame.f_locals:
                self.stop_tracing()
                params['**' + kwargs_name] = serialize(frame.f_locals[kwargs_name])
                self.start_tracing()
                
        return params
    
    def _get_current_function_name(self):
        """Get the name of the currently executing function"""
        if self.call_stack:
            return self.call_stack[-1]['qualified_name']
        return "<module>"
        
    def _get_function_info(self, frame):
        """Extract detailed function information"""
        func_name = frame.f_code.co_name
        func_qualname = get_func_qualname(frame, self.source_cache)
        filename = frame.f_code.co_filename
        line_no = frame.f_lineno
        module = inspect.getmodule(frame)        

        if module is None:
            mod_name = Path(filename).stem
        else:
            mod_name = module.__name__
            if mod_name == "__main__":
                module_file = getattr(module, "__file__", None)
                if module_file:
                    mod_name = Path(module_file).stem
                else:
                    mod_name = Path(filename).stem
        
        return {
            'qualified_name': '{}:{}'.format(mod_name, func_qualname),
            'filename': filename,
            'func_name': func_name,
            'mod_name': mod_name,
            'line_no': line_no
        }
    
    def _update_function_variables(self, frame):
        """Update the current function's variable dictionary with local variables"""
        if not self.function_variables_stack:
            return
            
        current_func_vars = self.function_variables_stack[-1]
        
        # Get the function's local variables (excluding globals and builtins)
        code = frame.f_code
        local_var_names = code.co_varnames
        
        # Update only local variables
        for var_name in local_var_names:
            if var_name in frame.f_locals:
                self.stop_tracing()
                current_func_vars[var_name] = serialize(frame.f_locals[var_name])
                self.start_tracing()
    
    def _get_current_seen_variables(self):
        """Get a copy of the current function's seen variables"""
        if self.function_variables_stack:
            return dict(self.function_variables_stack[-1])
        return {}
    
    def _add_trace_entry(self, event_type, frame, **kwargs):
        """Add a structured trace entry"""
        filename = frame.f_code.co_filename
        line_no = frame.f_lineno
        function_name = self._get_current_function_name()
        source_line = self._get_source_line(filename, line_no)
        
        entry = {
            'event_id': self.event_id,
            'event_type': event_type,
            'line_number': line_no,
            'statement': source_line,
            'filepath': filename,
            'function_name': function_name,
            **kwargs
        }
        self.event_id += 1
        
        self.trace_data.append(entry)

    def _trace_function(self, frame, event, arg):
        """The main tracing callback that dispatches events to their respective handlers."""
    
        if event == 'call' and frame.f_locals.get('self') is self:
            return None

        if _should_ignore(frame.f_code.co_filename, *self.include_stdlib):
            return self._trace_function

        if not self._is_function_allowed(frame):
            return self._trace_function
        
        if event == 'call':
            func_info = self._get_function_info(frame)
            self._handle_call_event(frame, func_info)
        elif event == 'return':
            self._handle_return_event(frame, arg)
        elif event == 'line':
            self._handle_line_event(frame)
        elif event == 'exception':
            self._handle_exception_event(frame, arg)
        return self._trace_function
    
    def _handle_call_event(self, frame, func_info):
        """Handles a 'call' event by managing stacks, computing parameter sources, and recording function entry."""
        # caller_snapshot = self._snapshot_caller_context()
        caller_snapshot = []
        # self._prepare_call_stacks()
        parameters = self._get_function_parameters(frame)
        func_vars = dict(parameters)
        self.function_variables_stack.append(func_vars)
        # parameter_sources = self._compute_parameter_sources(frame, func_info)
        parameter_sources = {}
        # self._update_call_graph(func_info)
        self.call_stack.append(func_info)
        self._record_function_entry(frame, func_info, parameters, parameter_sources, caller_snapshot)

    def _record_function_entry(self, frame, func_info, parameters, parameter_sources, caller_snapshot):
        """Records a 'Function' entry in the trace data and marks the definition event for its parameters."""
        self._add_trace_entry(
            'Function',
            frame,
            function_name=func_info['qualified_name'],
            caller_name=self.call_stack[-2]['qualified_name'] if len(self.call_stack) > 1 else "<module>",
            parameters=parameters,
            parameter_sources=parameter_sources if parameter_sources else {},
            inherited_control_dependencies=[
                e['id'] if e.get('truth') is not False else -e['id']
                for e in caller_snapshot
            ]
        )

        # Mark callee parameter definitions
        callee_qualified = func_info['qualified_name']
        code = frame.f_code
        param_count = code.co_argcount
        param_names = list(code.co_varnames[:param_count])
        if code.co_flags & 0x04:
            param_names.append(code.co_varnames[param_count])
            param_count += 1
        if code.co_flags & 0x08:
            param_names.append(code.co_varnames[param_count])

        for pname in param_names:
            self.last_def_event[callee_qualified][pname] = self.event_id - 1

    def _handle_return_event(self, frame, arg):
        """Handles a 'return' event by restoring caller state from stacks and recording the return."""
        if self.control_stack_stack:
            self.control_stack = self.control_stack_stack.pop()
        else:
            self.control_stack = []

        returning_func_name = self.call_stack[-1]['qualified_name'] if self.call_stack else "<module>"
        caller_name_after_return = (
            self.call_stack[-2]['qualified_name']
            if len(self.call_stack) > 1 else
            "<module>" if len(self.call_stack) == 1 else None
        )

        if self.call_stack:
            self.call_stack.pop()
            source_line = self._get_source_line(frame.f_code.co_filename, frame.f_lineno)
            _, vars_used = _get_vars_defined_and_used(source_line)
            # _, vars_used = [], []
            
            if self.function_variables_stack:
                self.function_variables_stack.pop()
            if self.inherited_control_stack:
                self.inherited_control_stack.pop()

            self.stop_tracing()
            self._add_trace_entry(
                'Return',
                frame,
                function_name=returning_func_name,
                vars_used=vars_used,
                caller_name=caller_name_after_return,
                return_value=serialize(arg)
            )
            self.start_tracing()

    def _handle_line_event(self, frame):
        """Handles a 'line' event by analyzing the line and dispatching to control or regular line handlers."""
        self._update_function_variables(frame)

        source_line = self._get_source_line(frame.f_code.co_filename, frame.f_lineno)
        vars_defined, vars_used = _get_vars_defined_and_used(source_line)
        control_deps = []
        inherited_ids = []
        
        self._handle_regular_line(frame, vars_defined, vars_used, control_deps, inherited_ids)

    def _handle_exception_event(self, frame, arg):
        """Handles an 'exception' event by recording the exception details in the trace."""
        if self.call_stack:
            exc_type, exc_value, exc_tb = arg
            source_line = self._get_source_line(frame.f_code.co_filename, frame.f_lineno)
            _, vars_used = _get_vars_defined_and_used(source_line)
            
            self._add_trace_entry(
                'Exception',
                frame,
                exception_type=exc_type.__name__,
                exception_value=str(exc_value),
                vars_used=vars_used or None
            )

    def _handle_regular_line(self, frame, vars_defined, vars_used, control_deps, inherited_ids):
        """Handles a regular line of code by recording a 'Line' event with its data dependencies."""
        seen_variables = self._get_current_seen_variables()
        self._add_trace_entry(
            'Line',
            frame,
            vars_defined=vars_defined,
            vars_used=vars_used,
            control_dependencies=control_deps,
            inherited_control_dependencies=inherited_ids,
            seen_variables=seen_variables
        )

        if vars_defined:
            self._update_last_definitions(vars_defined)

    def _update_last_definitions(self, vars_defined):
        """Updates the mapping of variable names to the event ID where they were last defined."""
        cur_qualified = self.call_stack[-1]['qualified_name'] if self.call_stack else "<module>"
        for v in vars_defined:
            self.last_def_event[cur_qualified][v] = self.event_id - 1

    def start_tracing(self):
        """Start the trace collection"""
        sys.settrace(self._trace_function)
        
    def stop_tracing(self):
        """Stop the trace collection"""
        sys.settrace(None)
        
    def save_trace(self):
        """Save the collected trace data to JSONL file"""
        # Ensure output directory exists
        base_dir = os.path.dirname(self.output_file)
        if base_dir:
            os.makedirs(base_dir, exist_ok=True)
        with open(self.output_file, 'w') as f:
            for entry in self.trace_data:
                json_line = dump(entry)
                f.write(json_line + '\n')
        print("Trace saved to {}".format(self.output_file), file=sys.stderr, flush=True)

class Tracker:
    def __init__(
        self,
        output_file,
        include_stdlib=None,
        allowed_functions=None,
    ):
        """
        :param output_file: Path to JSONL file where stacks will be stored.
        :param target_qualified_names: Iterable of qualified names to trace.
               Each must match the format produced by _get_function_info()['qualified_name'].
        :param include_stdlib: Optional set of path components to keep even if inside stdlib/site-packages.
        """
        self.output_file = output_file
        # self.target_qualified_names: Set[str] = set(target_qualified_names)
        self.allowed_functions = list(allowed_functions) if allowed_functions else []
        self.include_stdlib = list(include_stdlib) if include_stdlib else []

        # Each element is (target_qualified_name, stack_sig)
        # where stack_sig is a tuple of (filename, qualified_name) pairs.
        self.stack_samples = []
        self.stack_seen = set()
        self.source_cache = {}

    def __enter__(self):
        self.start_tracing()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.stop_tracing()
        try:
            self.save_trace()
        except Exception as e:
            print("Failed to save trace to {}: {}".format(self.output_file, e), file=sys.stderr, flush=True)
        return False

    def _get_function_info(self, frame):
        """
        Extract (minimal) function information for a frame.
        Returns:
          {
            'qualified_name': '<module>:<qualname>',
            'filename': '/abs/path/to/file.py',
            'func_name': 'foo',
            'mod_name': 'mypkg.module',
        }
        """
        func_name = frame.f_code.co_name
        func_qualname = get_func_qualname(frame, self.source_cache)
        filename = frame.f_code.co_filename
        module = inspect.getmodule(frame)

        if module is None:
            mod_name = Path(filename).stem
        else:
            mod_name = module.__name__
            if mod_name == "__main__":
                module_file = getattr(module, "__file__", None)
                if module_file:
                    mod_name = Path(module_file).stem
                else:
                    mod_name = Path(filename).stem

        return {
            'qualified_name': '{}:{}'.format(mod_name, func_qualname),
            'filename': filename,
            'func_name': func_name,
            'mod_name': mod_name,
        }

    def _is_function_allowed(self, frame):
        """
        Return True if this function should be traced, according to
        the functions file (if any). If no functions file is configured,
        trace everything (return True).
        """
        # No whitelist => trace everything
        if not self.allowed_functions:
            return True

        func_info = self._get_function_info(frame)
        return func_info["qualified_name"] in self.allowed_functions

    def _record_stack_to_target(self, target_qualified_name, frame):
        """
        Record the current call stack when a target function is called.

        Representation:
          stack = [
            (filename_root, qualified_name_root),
            ...,
            (filename_target, qualified_name_target)
          ]
        """
        stack = []
        cur = frame
        while cur is not None:
            info = self._get_function_info(cur)
            
            if not _should_ignore(info['filename'], *self.include_stdlib):
                stack.append((info['filename'], info['qualified_name']))
            cur = cur.f_back

        # Convert to root → leaf order
        stack.reverse()
        stack_sig = tuple(stack)

        key = (target_qualified_name, stack_sig)

        # Deduplicate (target, stack) pairs by exact structure
        if key not in self.stack_seen:
            self.stack_seen.add(key)
            self.stack_samples.append(key)

    def _trace_function(self, frame, event, arg):
        """
        sys.settrace callback.

        Behavior:
          - Ignore tracer's own methods.
          - Ignore frames from stdlib/site-packages unless whitelisted.
          - On 'call' events, if the function's qualified_name is one of the
            target_qualified_names, record the stack.
        """
        # Avoid tracing methods of this tracer instance
        if event == 'call' and frame.f_locals.get('self') is self:
            return None

        if _should_ignore(frame.f_code.co_filename, *self.include_stdlib):
            return self._trace_function

        if event == 'call':
            func_info = self._get_function_info(frame)
            self._handle_call_event(frame, func_info)

        return self._trace_function

    def start_tracing(self):
        """Start global tracing."""
        sys.settrace(self._trace_function)

    def stop_tracing(self):
        """Stop global tracing."""
        sys.settrace(None)
        
    def _handle_call_event(self, frame, func_info):
        if self._is_function_allowed(frame):
            qname = func_info['qualified_name']
            self._record_stack_to_target(qname, frame)

    def save_trace(self):
        """Persist the collected (target, stack) pairs to a JSONL file."""
        base_dir = os.path.dirname(self.output_file)
        if base_dir:
            os.makedirs(base_dir, exist_ok=True)

        with open(self.output_file, 'w', encoding='utf-8') as f:
            for target_qualified_name, stack_sig in self.stack_samples:
                entry = {
                    "target": target_qualified_name,
                    "stack": stack_sig,
                }
                json_line = dump(entry)
                f.write(json_line + '\n')

        print("Trace saved to {}".format(self.output_file), file=sys.stderr, flush=True)
