import io
import uuid
import types
import socket
import asyncio
import decimal
import datetime
import threading

from jsonpickle.handlers import BaseHandler, register
from tracer.serializer.ext.common import (
    PlainHandler,
)

class IteratorHandler(BaseHandler):
    def flatten(self, obj, data):
        return {"py/object": "__iterator__", "type": type(obj).__name__}
    
    def restore(self, obj):
        return obj

class GeneratorHandler(BaseHandler):
    def flatten(self, obj, data):
        return {"py/object": "__generator__", "name": getattr(obj, 'gi_code').co_name if hasattr(obj, 'gi_code') else type(obj).__name__}
    
    def restore(self, obj):
        return obj

class FileHandler(BaseHandler):
    def flatten(self, obj, data):
        try:
            name = obj.name
        except Exception:
            name = None
        return {"py/object": "io.IOBase", "name": name, "closed": obj.closed}
    
    def restore(self, obj):
        return obj

class TextIOHandler(BaseHandler):
    def flatten(self, obj, data):
        return {"py/object": "io.TextIOWrapper", "name": obj.name, "mode": obj.mode, "encoding": obj.encoding}
    
    def restore(self, obj):
        return obj

class SocketHandler(BaseHandler):
    def flatten(self, obj, data):
        return {"py/object": "socket.socket", "fd": obj.fileno(), "family": obj.family, "type": obj.type, "proto": obj.proto}
    
    def restore(self, obj):
        return obj

class DecimalHandler(BaseHandler):
    def flatten(self, obj, data):
        return {"py/object": "decimal.Decimal", "value": str(obj)}
    
    def restore(self, obj):
        return decimal.Decimal(obj["value"])

class PropertyHandler(BaseHandler):
    def flatten(self, obj, data):
        fn = obj.fget
        if fn:
            fn.__doc__ = obj.__doc__
        return self.context.flatten(fn, reset=False)
    
    def restore(self, obj):
        return obj

class UUIDHandler(BaseHandler):
    def flatten(self, obj, data):
        return {"py/object": "uuid.UUID"}
    
    def restore(self, obj):
        return obj

class DatetimeHandler(BaseHandler):
    def flatten(self, obj, data):
        # if obj is today, usually means some timestamp
        # we need to sanitize the hour, minute, second, microsecond
        # SPECIAL CASE: django tests use previous day and next day
        now = datetime.datetime.now(tz=obj.tzinfo)
        if (
            now.year == obj.year and
            now.month == obj.month and
            (
                now.day == obj.day or
                abs(now.day - obj.day) == 1
            )
        ):
            obj = obj.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "py/object": "datetime.datetime",
            "year": obj.year,
            "month": obj.month,
            "day": obj.day,
            "hour": obj.hour,
            "minute": obj.minute,
            "second": obj.second,
            "microsecond": obj.microsecond,
            "tzinfo": self.context.flatten(obj.tzinfo, reset=False),
            "fold": obj.fold
        }
    
    def restore(self, obj):
        return obj

class DateHandler(BaseHandler):
    def flatten(self, obj, data):
        return {
            "py/object": "datetime.date",
            "year": obj.year,
            "month": obj.month,
            "day": obj.day
        }
    
    def restore(self, obj):
        return datetime.date(
            year=obj["year"],
            month=obj["month"],
            day=obj["day"]
        )

class TimeHandler(BaseHandler):
    def flatten(self, obj, data):
        return {
            "py/object": "datetime.time",
            "hour": obj.hour,
            "minute": obj.minute,
            "second": obj.second,
            "microsecond": obj.microsecond,
            "tzinfo": self.context.flatten(obj.tzinfo, reset=False)
        }
    
    def restore(self, obj):
        return datetime.time(
            hour=obj["hour"],
            minute=obj["minute"],
            second=obj["second"],
            microsecond=obj["microsecond"],
            tzinfo=self.context.restore(obj["tzinfo"], reset=False),
        )

class ConditionHandler(BaseHandler):
    def flatten(self, obj, data):
        return {
            "py/object": "threading.Condition",
            "locked": self.context.flatten(obj._lock, reset=False),
        }
    
    def restore(self, obj):
        return obj

class FutureHandler(BaseHandler):
    def flatten(self, obj, data):
        return {
            "py/object": "asyncio.Future",
            "_state": obj._state,
            "_blocking": obj._blocking,
            "_asyncio_future_blocking": obj._asyncio_future_blocking,
        }
    
    def restore(self, obj):
        return obj

def register_handlers():
    register(type(iter([])), IteratorHandler)
    register(types.GeneratorType, GeneratorHandler)
    register(io.IOBase, FileHandler)
    register(io.TextIOWrapper, TextIOHandler)
    register(socket.socket, SocketHandler)
    register(decimal.Decimal, DecimalHandler)
    register(property, PropertyHandler)
    register(uuid.UUID, UUIDHandler)
    register(datetime.datetime, DatetimeHandler)
    register(datetime.date, DateHandler)
    register(datetime.time, TimeHandler)
    register(threading.Condition, ConditionHandler)
    register(asyncio.Future, FutureHandler)
    register(threading.Thread, PlainHandler)
    return [
        type(iter([])), types.GeneratorType, io.IOBase,
        io.TextIOWrapper, socket.socket, decimal.Decimal, property,
        uuid.UUID, datetime.datetime, datetime.date, datetime.time,
        threading.Condition, asyncio.Future, threading.Thread,
    ]
