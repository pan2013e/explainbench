from functools import partial

from tracer.serializer.ext.common import (
    PlainHandler,
    try_import,
    register_registry_handlers,
)

try_import_matplotlib = partial(try_import, registry='matplotlib')
register_handlers = partial(register_registry_handlers, registry='matplotlib')

try_import_matplotlib(
    "matplotlib.transforms",
    ["BboxBase"],
    PlainHandler,
    base=True,
)
try_import_matplotlib(
    "matplotlib.axis",
    ["Axis"],
    PlainHandler,
    base=True,
)