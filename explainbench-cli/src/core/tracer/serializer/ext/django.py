from functools import partial
from jsonpickle.handlers import BaseHandler
from tracer.serializer.ext.common import (
    PlainHandler,
    try_import,
    register_registry_handlers,
    canonical_class_name,
)

try_import_django = partial(try_import, registry='django')
register_handlers = partial(register_registry_handlers, registry='django')

class PaginatorHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "per_page": obj.per_page,
                "orphans": obj.orphans,
                "allow_empty_first_page": obj.allow_empty_first_page,
                "__dir__": dir(obj),
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

class DjangoSimpleTestCaseHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update({
                "client": self.context.flatten(obj.client, reset=False),
            })
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

class ImmutableListHandler(BaseHandler):
    def flatten(self, obj, data):
        try:
            result = self.context.flatten(list(obj), reset=False)
        except Exception:
            result = {"py/object": canonical_class_name(obj)}
        return result
    
    def restore(self, obj):
        return obj

class ModelHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            data = obj.__getstate__()
            data.pop("_state", None)
            data.pop("_django_version", None)
            data.pop("date_joined", None)
            data.pop("last_login", None)
            data.pop("password", None)
            data.pop("applied", None)
            result.update(self.context.flatten(data, reset=False))
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

class DjangoHttpResponseHeadersHandler(BaseHandler):
    HEADER_WHITELIST = (
        "Content-Type",
        "Content-Encoding",
        "Location",
        "Vary",
    )

    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result["status_code"] = getattr(obj, "status_code", None)
        except Exception:
            pass

        extracted = {}
        try:
            if hasattr(obj, "headers"):
                # Django 2.2+ (Mapping-like, case-insensitive)
                for key in self.HEADER_WHITELIST:
                    val = obj.headers.get(key)
                    if val is not None:
                        extracted[key] = str(val)
            elif hasattr(obj, "_headers"):
                # Older style: {lower: (orig, value)}
                h = getattr(obj, "_headers", {}) or {}
                for key in self.HEADER_WHITELIST:
                    lk = key.lower()
                    if lk in h and isinstance(h[lk], (tuple, list)) and len(h[lk]) == 2:
                        extracted[key] = str(h[lk][1])
        except Exception:
            pass

        if extracted:
            result["headers"] = extracted
            if "Content-Type" in extracted:
                result["content_type"] = extracted["Content-Type"]
            if "Content-Encoding" in extracted:
                result["content_encoding"] = extracted["Content-Encoding"]
            if "Location" in extracted:
                result["location"] = extracted["Location"]

        return result

    def restore(self, obj):
        return obj

class ExpressionHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update(self.context.flatten(obj.__getstate__(), reset=False))
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

class ParserHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            data = obj.__dict__.copy()
            data.pop("tags", None)
            data.pop("filters", None)
            result.update(self.context.flatten(data, reset=False))
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

class FieldHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            data = obj.__dict__.copy()
            data.pop("_get_default", None)
            result.update(self.context.flatten(data, reset=False))
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

class SafeMIMETextHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result["content_type"] = obj.get_content_type()
        except Exception:
            pass
        try:
            result["content_subtype"] = obj.get_content_subtype()
        except Exception:
            pass
        return result

    def restore(self, obj):
        return obj

class QuerySetHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result["model"] = obj.model._meta.label
        except Exception:
            pass
        try:
            result["db"] = obj.db
        except Exception:
            pass
        return result

    def restore(self, obj):
        return obj

class PromiseHandler(BaseHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            data = obj.__dict__.copy()
            result.update(self.context.flatten(data, reset=False))
        except Exception:
            pass
        return result

    def restore(self, obj):
        return obj

try_import_django(
    "django.db.models.query",
    ["QuerySet"],
    QuerySetHandler,
    base=True,
)
try_import_django(
    "django.core.paginator",
    ["Paginator"],
    PaginatorHandler,
    base=True,
)
try_import_django(
    "django.test",
    ["SimpleTestCase"],
    DjangoSimpleTestCaseHandler,
    base=True,
)
try_import_django(
    "django.utils.datastructures",
    ["ImmutableList"],
    ImmutableListHandler,
)
try_import_django(
    "django.db.models.base",
    ["Model"],
    ModelHandler,
    base=True,
)
try_import_django(
    "django.db.backends.base.base",
    ["BaseDatabaseWrapper"],
    PlainHandler,
    base=True,
)
try_import_django(
    "django.db.backends.sqlite3.base",
    ["DatabaseWrapper"],
    PlainHandler,
)
try_import_django(
    "django.contrib.admin.views.autocomplete",
    ["AutocompleteJsonView"],
    PlainHandler,
    base=True,
)
try_import_django(
    "django.http.response",
    ["HttpResponseBase"],
    DjangoHttpResponseHeadersHandler,
    base=True,
)
try_import_django(
    "http.cookies",
    ["SimpleCookie"],
    PlainHandler,
)
try_import_django(
    "django.core.management.base",
    ["BaseCommand"],
    PlainHandler,
    base=True,
)
try_import_django(
    "django.contrib.staticfiles.storage",
    ["ManifestStaticFilesStorage"],
    PlainHandler,
)
try_import_django(
    "django.db.models.expressions",
    ["BaseExpression"],
    ExpressionHandler,
    base=True,
)
try_import_django(
    "django.utils.connection",
    ["ConnectionProxy"],
    PlainHandler,
)
try_import_django(
    "django.db.utils",
    ["ConnectionHandler"],
    PlainHandler,
)
try_import_django(
    "django.template.base",
    ["Parser"],
    ParserHandler,
)
try_import_django(
    "django.template.library",
    ["Library"],
    PlainHandler,
)
try_import_django(
    "django.template.engine",
    ["Engine"],
    PlainHandler,
)
try_import_django(
    "django.db.models.fields",
    ["Field"],
    FieldHandler,
    base=True,
)
try_import_django(
    "django.core.mail.message",
    ["SafeMIMEText"],
    SafeMIMETextHandler,
)
try_import_django(
    "django.utils.functional",
    ["Promise"],
    PromiseHandler,
    base=True,
)