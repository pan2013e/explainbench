import io
import sys
import json
import inspect
import jsonpickle

from collections.abc import Mapping, Sequence, Set
from tracer.serializer.ext import (
    register_handlers,
    register_type_handlers,
)
from tracer.serializer.util import (
    PRIMITIVES,
    safe_hasattr,
    non_serializable,
    exception_guard,
    isolate_parameters,
)

if hasattr(sys, 'set_int_max_str_digits'):
    sys.set_int_max_str_digits(0)

def registry_get_monkey_patch(self):
    '''
    - Base handler is registered for type A
    - An instance of type B (subclass of A) is requested
    - Only return the base handler if A and B are defined in the same top module
    - Exception: allow cross-module base handler usage, if
      - A inherits from unittest.TestCase, 
      - A is from the django module (django test classes are not in the 'django' module)
    '''
    def is_same_module(cls_or_name, cls):
        cls_or_name_module = cls_or_name.__module__.split('.')[0]
        cls_module = cls.__module__.split('.')[0]
        return cls_or_name_module == cls_module
    
    def is_subclass_of_testcase(cls):
        from unittest import TestCase
        return issubclass(cls, TestCase)
    
    def is_from_django(cls):
        return cls.__module__.startswith('django.')
    
    def get(cls_or_name, default=None):
        handler = self._handlers.get(cls_or_name)
        # attempt to find a base class
        if handler is None and jsonpickle.util.is_type(cls_or_name):
            for cls, base_handler in self._base_handlers.items():
                if issubclass(cls_or_name, cls) and (
                    is_same_module(cls_or_name, cls) or
                    is_subclass_of_testcase(cls) or
                    is_from_django(cls)
                ):
                    return base_handler
        return default if handler is None else handler
    return get

jsonpickle.handlers.get = registry_get_monkey_patch(jsonpickle.handlers.registry)

REGISTERED_EXT_TYPES = register_handlers()
REGISTERED_EXT_CLS_TYPES = register_type_handlers()
PICKLER = jsonpickle.Pickler(warn=True, make_refs=False, max_depth=20)
UNPICKLER = jsonpickle.Unpickler()

def pickler_flatten_obj_monkey_patch(self):
    from jsonpickle.pickler import _in_cycle
    from tracer.serializer.ext.common import canonical_class_name
    
    def sanitized_repr(obj):
        return {"py/object": canonical_class_name(obj)}
        
    def _flatten_obj(obj):
        self._seen.append(obj)

        max_reached = self._max_reached()

        try:
            in_cycle = _in_cycle(obj, self._objs, max_reached, self.make_refs)
            if in_cycle:
                # break the cycle
                flatten_func = sanitized_repr
            else:
                flatten_func = self._get_flattener(obj)

            if flatten_func is None:
                self._pickle_warning(obj)
                return None

            return flatten_func(obj)

        except (KeyboardInterrupt, SystemExit) as e:
            raise e
        except Exception as e:
            if self.fail_safe is None:
                raise e
            else:
                return self.fail_safe(e)
    return _flatten_obj

PICKLER._flatten_obj = pickler_flatten_obj_monkey_patch(PICKLER)

def pickler_flatten_function_monkey_patch(self):
    def _flatten_function(obj):
        if self.unpicklable:
            name = jsonpickle.util.importable_name(obj)
            data = {jsonpickle.tags.FUNCTION: name}
            if not name.startswith('builtins.'):
                data['__doc__'] = obj.__doc__
        else:
            data = None
        return data
    return _flatten_function

PICKLER._flatten_function = pickler_flatten_function_monkey_patch(PICKLER)

def unpickler_restore_function_monkey_patch(self):
    def _restore_function(obj):
        return obj
    return _restore_function

UNPICKLER._restore_function = unpickler_restore_function_monkey_patch(UNPICKLER)

def pickler_mktyperef_monkey_patch(obj):
    for cls, flattener, base in REGISTERED_EXT_CLS_TYPES:
        if base:
            if issubclass(obj, cls):
                return flattener(obj)
        else:
            if obj is cls:
                return flattener(obj)
    return {jsonpickle.tags.TYPE: jsonpickle.util.importable_name(obj)}

jsonpickle.pickler._mktyperef = pickler_mktyperef_monkey_patch

@isolate_parameters
@exception_guard
def serialize(x):
    if isinstance(x, PRIMITIVES):
        if isinstance(x, float):
            if any([
                x != x,  # NaN
                x == float('inf'),
                x == float('-inf'),
            ]):
                return str(x)
        return x
    
    if isinstance(x, (*tuple(REGISTERED_EXT_TYPES), type)):
        return PICKLER.flatten(x)
    
    if isinstance(x, Mapping):
        out = {}
        for k, v in x.items():
            out[str(k)] = serialize(v)
        return out
    
    if isinstance(x, (Sequence, Set)):
        out = []
        for v in list(x):
            out.append(serialize(v))
        return out if not isinstance(x, tuple) else tuple(out)

    if any([
        inspect.isframe(x), inspect.iscode(x), inspect.istraceback(x),
        safe_hasattr(x, '__iter__') and not isinstance(x, (bytes, bytearray, io.IOBase)),
    ]):
        return non_serializable(x)
    
    return PICKLER.flatten(x)

def dump(x):
    return json.dumps(serialize(x))

def deserialize(x):
    try:
        return UNPICKLER.restore(x)
    except Exception:
        return x