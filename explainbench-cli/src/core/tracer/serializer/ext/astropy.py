import inspect

from functools import partial
from jsonpickle.handlers import BaseHandler
from tracer.serializer.ext.common import (
    PlainHandler,
    try_import,
    register_registry_handlers,
    canonical_class_name,
)

try_import_astropy = partial(try_import, registry='astropy')
register_handlers = partial(register_registry_handlers, registry='astropy')

def safe_hasattr(obj, attr):
    try:
        inspect.getattr_static(obj, attr)
        return True
    except AttributeError:
        return False

# Handlers adapted from Astropy's YAML serialization
# https://docs.astropy.org/en/latest/_modules/astropy/io/misc/yaml.html
class UnitHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        if safe_hasattr(obj, "to_string"):
            result["unit"] = obj.to_string()
        return result

    def restore(self, obj):
        return obj

class DataInfoHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update(
                self.context.flatten(obj._represent_as_dict(), reset=False)
            )
        except (AttributeError, KeyError, TypeError):
            pass
        return result

    def restore(self, obj):
        return obj

class GeneralAstropyHandler(BaseHandler):
    def flatten(self, obj, data):
        result =  {"py/object": canonical_class_name(obj)}
        try:
            result.update(
                self.context.flatten(obj.info._represent_as_dict(), reset=False)
            )
        except (AttributeError, KeyError, TypeError):
            pass
        return result

    def restore(self, obj):
        return obj

class ColumnHandler(BaseHandler):
    def flatten(self, obj, data):
        result =  {"py/object": canonical_class_name(obj)}
        try:
            result.update(
                self.context.flatten({
                    "data": obj.data,
                    "name": obj.name,
                    "unit": obj.unit,
                    "format": obj.format, 
                }, reset=False)
            )
        except AttributeError:
            pass
        return result

    def restore(self, obj):
        return obj

class RowHandler(BaseHandler):
    def flatten(self, obj, data):
        result =  {"py/object": canonical_class_name(obj)}
        try:
            result.update(
                self.context.flatten({
                    "data": obj.__array__(),
                }, reset=False)
            )
        except AttributeError:
            pass
        return result

    def restore(self, obj):
        return obj

class TableHandler(BaseHandler):
    def flatten(self, obj, data):
        result =  {"py/object": canonical_class_name(obj)}
        # Heuristics to detect if object instatiation is incomplete
        if not hasattr(obj, 'indices'):
            return result
        try:
            result.update(
                self.context.flatten({
                    "columns": obj.columns,
                    "masked": obj.masked,
                }, reset=False)
            )
        except AttributeError:
            pass
        return result

    def restore(self, obj):
        return obj

class TimeSeriesHandler(BaseHandler):
    def flatten(self, obj, data):
        result =  {"py/object": canonical_class_name(obj)}
        try:
            result.update(
                self.context.flatten({
                    "time": obj.time,
                }, reset=False)
            )
        except Exception:
            pass
        return result

    def restore(self, obj):
        return obj
    
class LexerHandler(BaseHandler):
    def flatten(self, obj, data):
        result =  {"py/object": canonical_class_name(obj)}
        try:
            result.update(obj.__dict__)
        except Exception:
            pass
        return result

    def restore(self, obj):
        return obj

class CompoundModelHandler(BaseHandler):
    def flatten(self, obj, data):
        result =  {"py/object": canonical_class_name(obj)}
        try:
            result.update(
                self.context.flatten({
                    "op": obj.op,
                    "left": obj.left,
                    "right": obj.right,
                    "param_names": obj.param_names,
                    "n_inputs": obj.n_inputs,
                    "n_outputs": obj.n_outputs,
                }, reset=False)
            )
        except Exception:
            pass
        return result

    def restore(self, obj):
        return obj

class WCSHandler(BaseHandler):
    def flatten(self, obj, data):
        result =  {"py/object": canonical_class_name(obj)}
        try:
            result.update(self.context.flatten(obj.__dict__, reset=False))
        except Exception:
            pass
        return result

    def restore(self, obj):
        return obj

class NdarrayMixinHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            import numpy as np
            result.update(
                self.context.flatten({
                    "base": np.array(obj),
                    "dtype": obj.dtype,
                    "shape": obj.shape,
                }, reset=False)
            )
            return result
        except Exception:
            pass

    def restore(self, obj):
        return obj

try_import_astropy(
    "astropy.units", 
    ["UnitBase", "FunctionUnitBase", "StructuredUnit"],
    UnitHandler,
    base=True,
)
try_import_astropy(
    "astropy.time",
    ["TimeInfo"],
    DataInfoHandler,
)
try_import_astropy(
    "astropy.table.column",
    ["ColumnInfo", "MaskedColumnInfo"],
    DataInfoHandler,
)
try_import_astropy(
    "astropy.units",
    ["QuantityInfo"],
    DataInfoHandler,
)
try_import_astropy(
    "astropy.coordinates.earth",
    ["EarthLocationInfo"],
    DataInfoHandler,
)
try_import_astropy(
    "astropy.table.ndarray_mixin",
    ["NdarrayMixin"],
    NdarrayMixinHandler,
)
try_import_astropy(
    "astropy.units", 
    ["Quantity", "Magnitude", "Dex", "Decibel"],
    GeneralAstropyHandler,
    base=True,
)
try_import_astropy(
    "astropy.coordinates",
    ["Angle", "Latitude", "Longitude"],
    GeneralAstropyHandler,
    base=True,
)
try_import_astropy(
    "astropy.coordinates",
    ["SkyCoord"],
    GeneralAstropyHandler,
    base=True,
)
try_import_astropy(
    "astropy.coordinates.earth",
    ["EarthLocation"],
    GeneralAstropyHandler,
    base=True,
)
try_import_astropy(
    "astropy.time",
    ["Time", "TimeDelta"],
    GeneralAstropyHandler,
)
try_import_astropy(
    "astropy.table.column",
    ["BaseColumn"],
    ColumnHandler,
    base=True,
)
try_import_astropy(
    "astropy.table",
    ["Row"],
    RowHandler,
)
try_import_astropy(
    "astropy.table",
    ["Table"],
    TableHandler,
    base=True,
)
try_import_astropy(
    "astropy.timeseries",
    ["TimeSeries"],
    TimeSeriesHandler,
)
try_import_astropy(
    "astropy.extern.ply.lex",
    ["Lexer"],
    LexerHandler,
)
try_import_astropy(
    "astropy.modeling.core",
    ["CompoundModel"],
    CompoundModelHandler,
    base=True,
)
try_import_astropy(
    "astropy.io.fits.tests.conftest",
    ["FitsTestCase"],
    PlainHandler,
    base=True,
)
try_import_astropy(
    "astropy.wcs.wcs",
    ["WCS"],
    WCSHandler,
)