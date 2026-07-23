from functools import partial

from jsonpickle.handlers import BaseHandler
from tracer.serializer.ext.common import (
    try_import,
    register_registry_handlers,
    canonical_class_name,
)

try_import_pytest = partial(try_import, registry='pytest')
register_handlers = partial(register_registry_handlers, registry='pytest')

class PytestPluginManagerHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            data = obj.__dict__.copy()
            data.pop("_name2plugin", None)
            data.pop("_plugin2hookcallers", None)
            data.pop("hook", None)
            result.update(self.context.flatten(data, reset=False))
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

try_import_pytest(
    "_pytest.config",
    ["PytestPluginManager"],
    PytestPluginManagerHandler,
)