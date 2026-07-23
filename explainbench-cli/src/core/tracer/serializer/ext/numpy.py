def register_handlers():
    try:
        import numpy as np
        from jsonpickle.ext import numpy as jsonpickle_numpy
        try:
            jsonpickle_numpy.register_handlers(ndarray_mode='ignore', ndarray_size_threshold=None)
        except Exception:
            from jsonpickle import register, unregister
            ndarray_handler = jsonpickle_numpy.NumpyNDArrayHandlerView(mode='ignore', size_threshold=None)
            jsonpickle_numpy.register_handlers()
            unregister(np.ndarray)
            register(np.ndarray, ndarray_handler)
        return [
            np.ndarray, np.dtype, np.generic, np.dtype(np.void).__class__,
            np.dtype(np.float32).__class__, np.dtype(np.int32).__class__,
            np.dtype(np.datetime64).__class__, np.datetime64,
        ]
    except ImportError:
        return []
