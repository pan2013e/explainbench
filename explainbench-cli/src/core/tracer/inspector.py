import os
import bdb
import sys
import json
import base64
import signal
import traceback
import multiprocessing as mp

from queue import Empty
from tracer.serializer import serialize
from tracer.util import get_func_qualname

__all__ = ['ExpressionInspector', 'encode_expr_list']

def encode_expr_list(exprs):
    encoded = base64.b64encode(json.dumps(exprs).encode()).decode()
    return 'b64:{}'.format(encoded)

def decode_expr_list(encoded):
    if not encoded.startswith('b64:'):
        raise ValueError("Invalid encoded expression list")
    b64 = encoded[4:]
    exprs = json.loads(base64.b64decode(b64))
    assert isinstance(exprs, list) and all(isinstance(e, str) for e in exprs)
    return exprs

def get_initial_state(mode):
    if mode == 'before':
        return BeforeExecution.Initialized
    elif mode == 'after':
        return AfterExecution.Initialized
    raise RuntimeError("unreachable")

# State Machine Diagram
# A. Non-return statement breakpoint
# A.1. Mode "after": Inspect expression after bp line is executed
#
#                 <bp reached>
#    INITIALIZED -------------> BREAKPOINT ------------> COMPLETED
#      ↖-----|     [set next]               [eval expr]    ↖---|
#  <bp not reached>
#
# A.2. Mode "before": Inspect expression before bp line is executed
#
#                      <bp reached>
#    INITIALIZED -----------------------> COMPLETED
#      ↖-----|          [eval expr]         ↖---|
#  <bp not reached>
#
# B. Return statement breakpoint: Same as A.2
#
# - bp: <file:line:count>, count is decremented on each hit until 0
# - when count is 0, the bp is considered "reached"
class State:
    @staticmethod
    def dispatch_line(dbg, frame):
        raise NotImplementedError("Must be implemented by subclasses")
    
    @staticmethod
    def dispatch_return(dbg, frame, return_value):
        raise NotImplementedError("Must be implemented by subclasses")

class Completed(State):
    @staticmethod
    def dispatch_line(dbg, frame):
        raise RuntimeError("Inspection already completed")
    
    @staticmethod
    def dispatch_return(dbg, frame, return_value):
        raise RuntimeError("Inspection already completed")

class AfterExecution:
    class Initialized(State):
        @staticmethod
        def dispatch_line(dbg, frame):
            if not dbg.break_here(frame):
                return AfterExecution.Initialized
            if not dbg.is_bp_func(frame):
                return AfterExecution.Initialized
            dbg.count -= 1
            if dbg.count > 0:
                return AfterExecution.Initialized
            dbg.set_next(frame)
            return AfterExecution.Breakpoint

        @staticmethod
        def dispatch_return(dbg, frame, return_value):
            if not dbg.break_here(frame):
                return AfterExecution.Initialized
            if not dbg.is_bp_func(frame):
                return AfterExecution.Initialized
            dbg.count -= 1
            if dbg.count > 0:
                return AfterExecution.Initialized
            frame.f_locals['__return__'] = return_value
            dbg.eval_expr(frame)
            return Completed
        
        @staticmethod
        def dispatch_exception(dbg, frame, exc_info):
            if not dbg.break_here(frame):
                etype, evalue, tb = exc_info
                dbg.result['exception'] = {
                    "stage": "exception before breakpoint",
                    "type": etype.__name__,
                    "message": str(evalue),
                    "traceback": traceback.format_tb(tb),
                }
                return AfterExecution.Initialized
            dbg.count -= 1
            if dbg.count > 0:
                return AfterExecution.Initialized
            frame.f_locals['__exception__'] = [exc_info[0].__name__, str(exc_info[1])]
            dbg.eval_expr(frame)
            return Completed

    class Breakpoint(State):
        @staticmethod
        def dispatch_line(dbg, frame):
            dbg.eval_expr(frame)
            return Completed
        
        @staticmethod
        def dispatch_return(dbg, frame, return_value):
            raise RuntimeError("unreachable")
        
        @staticmethod
        def dispatch_exception(dbg, frame, exc_info):
            raise RuntimeError("unreachable")

class BeforeExecution:
    class Initialized(State):
        @staticmethod
        def dispatch_line(dbg, frame):
            if not dbg.break_here(frame):
                return BeforeExecution.Initialized
            if not dbg.is_bp_func(frame):
                return BeforeExecution.Initialized
            dbg.count -= 1
            if dbg.count > 0:
                return BeforeExecution.Initialized
            dbg.eval_expr(frame)
            return Completed

        @staticmethod
        def dispatch_return(dbg, frame, return_value):
            if not dbg.break_here(frame):
                return BeforeExecution.Initialized
            if not dbg.is_bp_func(frame):
                return BeforeExecution.Initialized
            dbg.count -= 1
            if dbg.count > 0:
                return BeforeExecution.Initialized
            frame.f_locals['__return__'] = return_value
            dbg.eval_expr(frame)
            return Completed
        
        @staticmethod
        def dispatch_exception(dbg, frame, exc_info):
            if not dbg.break_here(frame):
                etype, evalue, tb = exc_info
                dbg.result['exception'] = {
                    "stage": "exception before breakpoint",
                    "type": etype.__name__,
                    "message": str(evalue),
                    "traceback": traceback.format_tb(tb),
                }
                return BeforeExecution.Initialized
            dbg.count -= 1
            if dbg.count > 0:
                return BeforeExecution.Initialized
            frame.f_locals['__exception__'] = [exc_info[0].__name__, str(exc_info[1])]
            dbg.eval_expr(frame)
            return Completed

class ExpressionInspector(bdb.Bdb):
    def __init__(self, bp_file, bp_line, expr, save_path=None, count=1, mode='before', bp_func_name=None):
        super().__init__()
        assert os.path.isabs(bp_file), "bp_file must be an absolute path"
        assert os.path.exists(bp_file), "bp_file must exist"
        assert bp_line > 0, "bp_line must be positive"
        assert count > 0, "count must be positive"
        assert mode in ['before', 'after'], "mode must be 'before' or 'after'"
        self.state = get_initial_state(mode)
        self.expr = self._init_expr(expr)
        self.save_path = save_path
        self.count = count
        self.mode = mode
        self.bp_func_name = bp_func_name
        self.source_cache = {}
        self.result = {
            'mode': self.mode,
            'file': bp_file,
            'line': bp_line,
            'count': self.count,
            'expr': self.expr,
            'value': None,
            'exception': {
                'stage': 'not reached',
                'type': None,
                'message': None,
                'traceback': None,
            },
        }
        self.clear_all_breaks()
        if self._check_expr():
            self.set_break(filename=bp_file, lineno=bp_line)
    
    def __enter__(self):
        self.set_trace()
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.save_result()
        return True # Suppress exceptions
    
    def user_line(self, frame):
        self.state = self.state.dispatch_line(self, frame)
    
    def user_return(self, frame, return_value):
        self.state = self.state.dispatch_return(self, frame, return_value)
    
    def user_exception(self, frame, exc_info):
        self.state = self.state.dispatch_exception(self, frame, exc_info)
    
    def is_bp_func(self, frame):
        if self.bp_func_name is None:
            return True
        return get_func_qualname(frame, self.source_cache) == self.bp_func_name

    def _init_expr(self, expr):
        if isinstance(expr, list):
            return expr
        assert isinstance(expr, str)
        try:
            return decode_expr_list(expr)
        except Exception:
            return [expr]
    
    def _check_expr(self):
        if self.mode == 'before':
            if (
                all('__exception__' in expr or '__return__' in expr for expr in self.expr)
                or all('__exception__' not in expr and '__return__' not in expr for expr in self.expr)
            ):
                return True
            self.result['exception'] = {
                'stage': 'initialization',
                'type': 'ValueError',
                'message': "Mixed expressions with and without __exception__/__return__",
                'traceback': [],
            }
            return False
        else:
            return True
    
    @staticmethod
    def fork_eval(queue, frame, expr, idx, timeout=60):
        def _timeout_handler(signum, frame):
            raise TimeoutError("Expression evaluation timed out")
        
        if '__return__' in expr and '__exception__' in frame.f_locals:
            expr = '__exception__'
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout)
        try:
            value = eval(expr, frame.f_globals, frame.f_locals)
            serialized = serialize(value)
            queue.put({
                'idx': idx,
                'value': serialized,
                'exception': None,
            })
        except Exception as e:
            queue.put({
                'idx': idx,
                'value': None,
                'exception': {
                    'stage': 'evaluation',
                    'type': type(e).__name__,
                    'message': str(e),
                    'traceback': traceback.format_tb(e.__traceback__),
                }
            })
        finally:
            signal.alarm(0)
    
    def eval_expr(self, frame, timeout=60):
        queue = mp.Queue()
        procs = []
        for idx, expr in enumerate(self.expr):
            p = mp.Process(target=self.fork_eval, args=(queue, frame, expr, idx, timeout))
            p.start()
            procs.append(p)
        results_by_idx = {}
        for idx, p in enumerate(procs):
            p.join(timeout)
            if p.is_alive():
                p.terminate()
                p.join()
                results_by_idx[idx] = {
                    'idx': idx,
                    'value': None,
                    'exception': {
                        'stage': 'evaluation',
                        'type': 'TimeoutError',
                        'message': "Expression evaluation timed out",
                        'traceback': [],
                    },
                }
        while True:
            try:
                result = queue.get_nowait()
            except Empty:
                break
            results_by_idx.setdefault(result['idx'], result)
        results = []
        for idx in range(len(self.expr)):
            results.append(results_by_idx.get(idx, {
                'idx': idx,
                'value': None,
                'exception': {
                    'stage': 'evaluation',
                    'type': 'RuntimeError',
                    'message': "Missing evaluation result",
                    'traceback': [],
                },
            }))
        self.result['value'] = []
        self.result['exception'] = []
        for result in results:
            if result['exception'] is None:
                self.result['value'].append(result['value'])
                self.result['exception'].append(None)
            else:
                self.result['value'].append(None)
                self.result['exception'].append(result['exception'])   
        self.set_quit()
    
    def save_result(self):
        if not self.save_path:
            return
        base_dir = os.path.dirname(self.save_path)
        if not os.path.exists(base_dir):
            os.makedirs(base_dir, exist_ok=True)
        with open(self.save_path, 'w', encoding='utf-8') as f:
            json.dump(self.result, f, indent=2)
        print("Expression value saved to {}".format(self.save_path), file=sys.stderr, flush=True)
