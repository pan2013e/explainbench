import warnings

from collections import defaultdict
from jsonpickle.handlers import BaseHandler, register

REGISTRIES = defaultdict(list)

def canonical_class_name(obj):
    return "{}.{}".format(obj.__class__.__module__, obj.__class__.__qualname__)

class PlainHandler(BaseHandler):
    def flatten(self, obj, data):
        return {"py/object": canonical_class_name(obj)}
    
    def restore(self, obj):
        return obj

def _try_import_impl(mod_name, class_names, handler, registry, base=False):
    assert registry != 'type', "Registry 'type' is reserved for type handlers."
    for class_name in class_names:
        try:
            mod = __import__(mod_name, fromlist=[class_name])
            if hasattr(mod, class_name):
                cls = getattr(mod, class_name)
                REGISTRIES[registry].append((cls, handler, base))
        except ImportError:
            pass
        except Exception as e:
            print("Error when importing {}.{}: {} - {}".format(mod_name, class_name, type(e).__name__, e))

def _try_import_type_impl(mod_name, class_names, handler_fn, base=False):
    for class_name in class_names:
        try:
            mod = __import__(mod_name, fromlist=[class_name])
            if hasattr(mod, class_name):
                cls = getattr(mod, class_name)
                REGISTRIES['type'].append((cls, handler_fn, base))
        except ImportError:
            pass
        except Exception as e:
            print("Error when importing type of {}.{}: {} - {}".format(mod_name, class_name, type(e).__name__, e))

def try_import(mod_name, class_names, handler, registry, base=False):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _try_import_impl(mod_name, class_names, handler, registry, base=base)

def try_import_type(mod_name, class_names, handler_fn, base=False):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _try_import_type_impl(mod_name, class_names, handler_fn, base=base)

def register_registry_handlers(registry):
    for cls, handler, base in REGISTRIES[registry]:
        register(cls, handler, base=base)
    return [cls for cls, _, _ in REGISTRIES[registry]]

def register_type_handlers():
    return REGISTRIES['type']