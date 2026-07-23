from functools import partial
from tracer.serializer.ext.common import (
    PlainHandler,
    canonical_class_name,
    try_import,
    register_registry_handlers,
)

try_import_sklearn = partial(try_import, registry='sklearn')
register_handlers = partial(register_registry_handlers, registry='sklearn')

class BaseSearchCVHandler(PlainHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            data = obj.__dict__.copy()
            data["refit_time_"] = "<omitted-by-serializer>"
            serialized = self.context.flatten(data, reset=False)
            if "cv_results_" in serialized and isinstance(serialized["cv_results_"], dict):
                serialized["cv_results_"].pop("mean_fit_time", None)
                serialized["cv_results_"].pop("std_fit_time", None)
                serialized["cv_results_"].pop("mean_score_time", None)
                serialized["cv_results_"].pop("std_score_time", None)
            result.update(serialized)
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

class IsolationForestHandler(PlainHandler):
    def flatten(self, obj, data):
        result = {"py/object": canonical_class_name(obj)}
        try:
            result.update(self.context.flatten({
                "n_estimators": obj.n_estimators,
                "max_samples": obj.max_samples,
                "max_features": obj.max_features,
                "bootstrap": obj.bootstrap,
                "bootstrap_features": obj.bootstrap_features,
                "oob_score": obj.oob_score,
                "warm_start": obj.warm_start,
                "verbose": obj.verbose,
            }, reset=False))
            if hasattr(obj, "offset_"):
                result["offset_"] =self.context.flatten(obj.offset_, reset=False)
        except Exception:
            pass
        return result
    
    def restore(self, obj):
        return obj

try_import_sklearn(
    "sklearn.externals.joblib.memory",
    ["Memory"],
    PlainHandler,
)
try_import_sklearn(
    "sklearn.model_selection._search",
    ["BaseSearchCV"],
    BaseSearchCVHandler,
    base=True,
)
try_import_sklearn(
    "sklearn.ensemble._iforest",
    ["IsolationForest"],
    IsolationForestHandler,
)
