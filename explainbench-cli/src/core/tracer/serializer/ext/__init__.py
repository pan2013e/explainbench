import os
import pkgutil
import importlib

__all__ = ['register_handlers', 'register_type_handlers']

def register_handlers():
    registered_types = []
    dir = os.path.abspath(os.path.dirname(__file__))
    for _, modname, _ in pkgutil.iter_modules([dir]):
        module = importlib.import_module('tracer.serializer.ext.{}'.format(modname))
        if hasattr(module, 'register_handlers'):
            registered_types.extend(module.register_handlers() or [])
    return registered_types

def register_type_handlers():
    from tracer.serializer.ext.common import register_type_handlers as _register
    dir = os.path.abspath(os.path.dirname(__file__))
    for _, modname, _ in pkgutil.iter_modules([dir]):
        importlib.import_module('tracer.serializer.ext.{}'.format(modname))
    return _register()
