from functools import partial
from jsonpickle.handlers import BaseHandler
from tracer.serializer.ext.common import (
    try_import,
    register_registry_handlers,
    canonical_class_name,
)

try_import_numpy = partial(try_import, registry='numpy_ext')
register_handlers = partial(register_registry_handlers, registry='numpy_ext')

class MaskedArrayHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "data": obj.data.tolist(),
                "mask": obj.mask.tolist(),
                "fill_value": obj.fill_value.tolist(),
                "dtype": self.context.flatten(obj.dtype, reset=False),
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            from numpy.ma import MaskedArray
            return MaskedArray(
                data=obj['data'],
                mask=obj['mask'],
                fill_value=obj['fill_value'],
                dtype=self.context.restore(obj['dtype'], reset=False),
            )
        except Exception:
            return obj

class NumpyBoolHandler(BaseHandler):
    def flatten(self, obj, data):
        return bool(obj)
    
    def restore(self, obj):
        return obj

try_import_numpy(
    "numpy.ma",
    ["MaskedArray"],
    MaskedArrayHandler,
)
try_import_numpy(
    "numpy",
    ["bool_"],
    NumpyBoolHandler,
)