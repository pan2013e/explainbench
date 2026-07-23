from functools import partial
from jsonpickle.handlers import BaseHandler
from tracer.serializer.ext.common import (
    PlainHandler,
    try_import,
    register_registry_handlers,
    canonical_class_name,
)

try_import_sympy = partial(try_import, registry='sympy')
register_handlers = partial(register_registry_handlers, registry='sympy')

def dict_keys_to_int(d):
    if not isinstance(d, dict):
        return d
    new_dict = {}
    for k, v in d.items():
        try:
            int_k = int(k)
        except (ValueError, TypeError):
            int_k = k
        new_dict[int_k] = dict_keys_to_int(v)
    return new_dict

class DomainHandler(BaseHandler):
    def flatten(self, obj, data):
        return {"py/object": canonical_class_name(obj)}
    
    def restore(self, obj):
        try:
            cls_str = obj["py/object"]
            mod_name, class_name = cls_str.rsplit(".", 1)
            mod = __import__(mod_name, fromlist=[class_name])
            cls = getattr(mod, class_name)
            return cls()
        except Exception:
            return obj

class RationalHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({"p": obj.p, "q": obj.q})
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            from sympy import Rational
            return Rational(obj["p"], obj["q"])
        except Exception:
            return obj

class IntegerHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({"p": obj.p})
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            from sympy import Integer
            return Integer(obj["p"])
        except Exception:
            return obj

class FloatHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "_mpf_": self.context.flatten(obj._mpf_, reset=False),
                "_prec": self.context.flatten(obj._prec, reset=False),
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            from sympy import Float
            return Float(
                num=self.context.restore(obj["_mpf_"], reset=False),
                precision=obj["_prec"],
            )
        except Exception:
            return obj

class SpecialNumberHandler(BaseHandler):
    def flatten(self, obj, data):
        return {"py/object": canonical_class_name(obj)}
    
    def restore(self, obj):
        try:
            from sympy import S
            cls_name = obj["py/object"].rsplit(".", 1)[-1]
            return getattr(S, cls_name)
        except Exception:
            return obj

class StringifyHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({"__str__": str(obj)})
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            cls_str = obj["py/object"]
            mod_name, class_name = cls_str.rsplit(".", 1)
            mod = __import__(mod_name, fromlist=[class_name])
            cls = getattr(mod, class_name)
            return cls(obj["__str__"])
        except Exception:
            return obj

class SymbolHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "name": obj.name,
                "_assumptions_orig": self.context.flatten(obj._assumptions_orig, reset=False),
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            from sympy import Symbol
            return Symbol(name=obj["name"], **obj["_assumptions_orig"])
        except Exception:
            return obj

class MatrixSymbolHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "name": obj.name,
                "shape": [self.context.flatten(dim, reset=False) for dim in obj.shape],
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            from sympy import MatrixSymbol
            shape = tuple(self.context.restore(obj["shape"], reset=False))
            return MatrixSymbol(obj["name"], *shape)
        except Exception:
            return obj

class QuaternionHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "a": obj.a,
                "b": obj.b,
                "c": obj.c,
                "d": obj.d,
                "_real_field": obj._real_field,
                "_norm": obj._norm,
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            from sympy import Quaternion
            return Quaternion(
                a=obj["a"], b=obj["b"], c=obj["c"], d=obj["d"],
                real_field=obj["_real_field"],
                norm=obj["_norm"],
            )
        except Exception:
            return obj

class DMPHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        if result["py/object"] == 'sympy.polys.polyclasses.DMP_Python':
            try:
                result.update({
                    "_rep": self.context.flatten(obj._rep, reset=False),
                    "dom": self.context.flatten(obj.dom, reset=False),
                    "lev": self.context.flatten(obj.lev, reset=False),
                })
            except Exception:
                pass
        return result
    
    def restore(self, obj):
        if obj["py/object"] != 'sympy.polys.polyclasses.DMP_Python':
            return obj
        try:
            from sympy.polys.polyclasses import DMP
            rep = self.context.restore(obj["_rep"], reset=False)
            dom = self.context.restore(obj["dom"], reset=False)
            lev = self.context.restore(obj["lev"], reset=False)
            return DMP(rep, dom, lev)
        except Exception:
            return obj

class PolyHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "rep": self.context.flatten(obj.rep, reset=False),
                "gens": [self.context.flatten(gen, reset=False) for gen in obj.gens],
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            cls_str = obj["py/object"]
            mod_name, class_name = cls_str.rsplit(".", 1)
            mod = __import__(mod_name, fromlist=[class_name])
            cls = getattr(mod, class_name)
            rep = self.context.restore(obj["rep"], reset=False)
            gens = tuple(self.context.restore(obj["gens"], reset=False))
            return cls.new(rep, *gens)
        except Exception:
            return obj

class DomainMatrixHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "rep": self.context.flatten(obj.rep, reset=False),
                "shape": self.context.flatten([self.context.flatten(dim, reset=False) for dim in obj.shape], reset=False),
                "domain": self.context.flatten(obj.domain, reset=False),
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            from sympy.polys.matrices import DomainMatrix
            rep = self.context.restore(obj["rep"], reset=False)
            rep = dict_keys_to_int(rep)
            shape = tuple(self.context.restore(obj["shape"], reset=False))
            domain = self.context.restore(obj["domain"], reset=False)
            return DomainMatrix(rep, shape, domain)
        except Exception:
            return obj

class RepMatrixHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "_rep": self.context.flatten(obj._rep, reset=False),
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            cls_str = obj["py/object"]
            mod_name, class_name = cls_str.rsplit(".", 1)
            mod = __import__(mod_name, fromlist=[class_name])
            cls = getattr(mod, class_name)
            rep = self.context.restore(obj["_rep"], reset=False)
            return cls._fromrep(rep)
        except Exception:
            return obj

# Universal handler for all sympy objects that can be returned by sympify
# If previous handlers miss, this handler will be used as the fallback
class BasicHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({"args": [self.context.flatten(arg, reset=False) for arg in obj.args]})
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        try:
            cls_str = obj["py/object"]
            mod_name, class_name = cls_str.rsplit(".", 1)
            mod = __import__(mod_name, fromlist=[class_name])
            cls = getattr(mod, class_name)
            args = tuple(self.context.restore(obj["args"], reset=False))
            return cls(*args)
        except Exception:
            return obj

class UnitSystemHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            data = obj.__dict__.copy()
            data.pop("_units", None)
            data.pop("_base_units", None)
            data.pop("_derived_units", None)
            data.pop("_quantity_dimension_map", None)
            data.pop("_quantity_scale_factors", None)
            result.update(self.context.flatten(data, reset=False))
        except Exception:
            pass
        return result

    def restore(self, obj):
        return obj

class VectorHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            if hasattr(obj, "args"):
                result["args"] = self.context.flatten(obj.args, reset=False)
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

try_import_sympy(
    "sympy",
    ["Domain"],
    DomainHandler,
    base=True,
)
try_import_sympy(
    "sympy",
    ["Rational"],
    RationalHandler,
    base=True,
)
try_import_sympy(
    "sympy",
    ["Integer"],
    IntegerHandler,
    base=True,
)
try_import_sympy(
    "sympy",
    ["Float"],
    FloatHandler,
)
try_import_sympy(
    "sympy.core.numbers",
    ["Infinity", "NegativeInfinity", "NaN", "ComplexInfinity", "Exp1", "Pi", "ImaginaryUnit"],
    SpecialNumberHandler,
)
try_import_sympy(
    "mpmath",
    ["mpf"],
    StringifyHandler,
)
try_import_sympy(
    "sympy",
    ["Symbol"],
    SymbolHandler,
)
try_import_sympy(
    "sympy",
    ["MatrixSymbol"],
    MatrixSymbolHandler,
)
try_import_sympy(
    "sympy",
    ["Quaternion"],
    QuaternionHandler,
)
try_import_sympy(
    "sympy.polys.polyclasses",
    ["DMP", "DMP_Python"],
    DMPHandler,
)
try_import_sympy(
    "sympy",
    ["Poly"],
    PolyHandler,
)
try_import_sympy(
    "sympy.polys.matrices",
    ["DomainMatrix"],
    DomainMatrixHandler,
)
try_import_sympy(
    "sympy.matrices.repmatrix",
    ["RepMatrix"],
    RepMatrixHandler,
    base=True,
)
try_import_sympy(
    "sympy.physics.units.dimensions",
    ["DimensionSystem"],
    PlainHandler,
)
try_import_sympy(
    "sympy",
    ["Basic",],
    BasicHandler,
    base=True
)
try_import_sympy(
    "sympy.physics.vector.vector",
    ["Vector"],
    VectorHandler,
)