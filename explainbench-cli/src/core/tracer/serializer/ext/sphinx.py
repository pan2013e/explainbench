from functools import partial

from jsonpickle.handlers import BaseHandler
from jsonpickle.util import importable_name
from tracer.serializer.ext.common import (
    PlainHandler,
    try_import,
    try_import_type,
    register_registry_handlers,
    canonical_class_name,
)

try_import_sphinx = partial(try_import, registry='sphinx')
register_handlers = partial(register_registry_handlers, registry='sphinx')

class MessageHandler(BaseHandler):
    def flatten(self, obj, data):
        results = {"py/object": canonical_class_name(obj)}
        try:
            results.update({
                "text": obj.text,
                "locations": self.context.flatten(obj.locations, reset=False),
            })
        except Exception:
            pass
        return results

    def restore(self, obj):
        return obj

class EventManagerHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            data = obj.__dict__.copy()
            data.pop("listeners", None)
            result.update(self.context.flatten(data, reset=False))
        except Exception:
            pass
        return result

    def restore(self, obj):
        return obj

def mockobject_cls_flattener(cls):
    cls_name = importable_name(cls)
    results = {"py/type": cls_name}
    if cls_name == "sphinx.ext.autodoc.mock._MockObject":
        return results
    try:
        results.update(cls.__dict__)
        if "__doc__" in results:
            del results["__doc__"]
    except Exception:
        pass
    return results

try_import_sphinx(
    "sphinx.testing.util",
    ["SphinxTestApp"],
    PlainHandler,
    base=True,
)
try_import_sphinx(
    "sphinx.io",
    ["SphinxBaseReader"],
    PlainHandler,
    base=True,
)
try_import_sphinx(
    "sphinx.parsers",
    ["Parser"],
    PlainHandler,
    base=True,
)
try_import_sphinx(
    "sphinx.builders",
    ["Builder"],
    PlainHandler,
    base=True,
)
try_import_sphinx(
    "sphinx.builders.gettext",
    ["Message"],
    MessageHandler,
)
try_import_sphinx(
    "docutils.parsers.rst.states",
    ["RSTStateMachine", "RSTState", "Inliner", "Body"],
    PlainHandler,
    base=True,
)
try_import_type(
    "sphinx.ext.autodoc.mock",
    ["_MockObject"],
    mockobject_cls_flattener,
    base=True,
)
try_import_sphinx(
    "sphinx.events",
    ["EventManager"],
    EventManagerHandler,
)
try_import_sphinx(
    "sphinx.config",
    ["Config"],
    PlainHandler,
)
try_import_sphinx(
    "sphinx.environment",
    ["BuildEnvironment"],
    PlainHandler,
)