from functools import partial

from tracer.serializer.ext.common import (
    PlainHandler,
    try_import,
    register_registry_handlers,
)

try_import_pylint = partial(try_import, registry='pylint')
register_handlers = partial(register_registry_handlers, registry='pylint')

try_import_pylint(
    "pylint.lint.pylinter",
    ["PyLinter"],
    PlainHandler,
)