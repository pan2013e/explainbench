import sys
import pickle
import inspect

from itertools import count
from functools import wraps, partial

PRIMITIVES = (type(None), bool, int, float, str)

def safe_hasattr(obj, attr):
    try:
        inspect.getattr_static(obj, attr)
        return True
    except AttributeError:
        return False

def non_serializable(obj, exc=None):
    if exc:
        msg = str(exc)
        if isinstance(exc, UserWarning) and '<lambda>' not in msg:
            print(msg, file=sys.stderr, flush=True)
        else:
            print('Object of type "{}" is non-serializable due to {}: {}'.format(type(obj).__name__, type(exc).__name__, msg), file=sys.stderr, flush=True)
    return "<{}>".format(type(obj).__name__)

def get_stackdepth(size=2):
    if sys._getframe().f_back.f_back is None:
        return 1
    frame = sys._getframe(size)
    for size in count(size):
        frame = frame.f_back
        if not frame:
            return size

def _exception_guard(func, max_depth=200):
    @wraps(func)
    def wrapper(x):
        recursion_limit = sys.getrecursionlimit()
        new_limit = min(recursion_limit, get_stackdepth() + max_depth)
        try:
            if new_limit < recursion_limit:
                sys.setrecursionlimit(new_limit)
            return func(x)
        except Exception as e:
            return non_serializable(x, e)
        finally:
            if sys.getrecursionlimit() != recursion_limit:
                sys.setrecursionlimit(recursion_limit)
    return wrapper

exception_guard = partial(_exception_guard, max_depth=200)

def inherits_numpy(cls):
    return any(
        _cls.__module__ and _cls.__module__.startswith('numpy')
        for _cls in cls.__mro__
    )

def safe_copy(obj):
    if any([
        isinstance(obj, PRIMITIVES),
        inherits_numpy(obj.__class__),
    ]):
        return obj
    try:
        return pickle.loads(pickle.dumps(obj, pickle.HIGHEST_PROTOCOL))
    except Exception:
        return obj

def isolate_parameters(func):
    @wraps(func)
    def wrapper(x):
        _x = safe_copy(x)
        return func(_x)
    return wrapper
