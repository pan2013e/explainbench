from typing import Iterable, Optional, Set, Dict
from deepdiff import DeepDiff
from collections.abc import Sequence

BASE_IGNORE_FIELDS: Set[str] = {"vars_used", "vars_defined"}
IGNORE_ORDER_REGISTRY: Dict[str, Set[str]] = {
    "astropy": {"attr_names"},
}

def make_ignore_order_func(extra_fields: Optional[Iterable[str]] = None):
    targets: Set[str] = set(BASE_IGNORE_FIELDS)
    if extra_fields:
        targets.update(extra_fields)

    def is_ordered_iterable(x):
        return isinstance(x, Sequence) and not isinstance(x, (str, bytes, bytearray))

    def func(level) -> bool:
        if not any(is_ordered_iterable(v) for v in (getattr(level, "t1", None), getattr(level, "t2", None))):
            return False
        segments = level.path(output_format="list")  # e.g., ['root','seen_variables','attr_names']
        last_key = next((s for s in reversed(segments) if isinstance(s, str)), None)
        return last_key in targets
    return func

def get_ignore_order_func(repo: Optional[str]):
    extra = IGNORE_ORDER_REGISTRY.get(repo, set()) # type: ignore
    return make_ignore_order_func(extra_fields=extra)


