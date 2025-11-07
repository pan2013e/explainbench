import re
from typing import Iterable, Optional, Set, Dict, Callable, Any, Iterator, Tuple
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

_BRACKETED_NAME_RE = re.compile(r"\[['\"]([^'\"]+)['\"]\]")
_VAR_NAME_INDEX = 1

def extract_var_name(full_path: str) -> str:
    tokens = _BRACKETED_NAME_RE.findall(str(full_path))
    if len(tokens) > _VAR_NAME_INDEX:
        return tokens[_VAR_NAME_INDEX]
    return ""  # safe fallback

def iter_diff_items(diffs_by_kind: Dict[str, Any]) -> Iterator[Tuple[str, str, Any]]:
    for change_kind, changes_for_kind in (diffs_by_kind or {}).items():
        if isinstance(changes_for_kind, dict):
            for full_path, payload in changes_for_kind.items():
                yield change_kind, full_path, payload
        elif isinstance(changes_for_kind, list):
            for payload in changes_for_kind:
                yield change_kind, payload, payload

def count_changed_vars(diffs_by_kind: Dict[str, Any]) -> int:
    n_var = 0
    for _ in iter_diff_items(diffs_by_kind):
        n_var += 1
    return n_var

def _filter_by_predicate(
    diff_dict: Dict[str, Any],
    keep: Callable[[str, str, Any], bool]
) -> Dict[str, Any]:
    """Return a new diffs-by-kind dict keeping only entries where keep(kind, path, payload) is True."""
    if not diff_dict:
        return {}
    out: Dict[str, Any] = {}
    for change_key, change_val in diff_dict.items():
        if isinstance(change_val, dict):
            kept = {}
            for full_path, payload in change_val.items():
                if keep(change_key, full_path, payload):
                    kept[full_path] = payload
            if kept:
                out[change_key] = kept
        elif isinstance(change_val, list):
            kept_list = []
            for payload in change_val:
                path_like = str(payload)
                if keep(change_key, path_like, payload):
                    kept_list.append(payload)
            if kept_list:
                out[change_key] = kept_list
    return out

def filter_added_dict_based_on_seen_variables(diff_dict: Dict[str, Any], event) -> Dict[str, Any]:
    """
    only process 'dictionary_item_added' entries; keep other change_key unchanged.
    Keep added entries whose var is NOT in event.seen_variables.
    """
    if not diff_dict:
        return {}
    seen = getattr(event, "seen_variables", {}) or {}

    def keep(kind: str, path: str, payload: Any) -> bool:
        if kind != "dictionary_item_added":
            return True  # preserve non-addition kinds
        var_name = extract_var_name(path)
        # keep only if var NOT already seen
        return var_name and (var_name not in seen)

    return _filter_by_predicate(diff_dict, keep)

def filter_based_on_vars_at_current_line(diff_dict: Dict[str, Any], event) -> Dict[str, Any]:
    """
    Keep entries whose var is referenced on the current line:
    referenced_vars = vars_used ∪ vars_defined
    """
    referenced = set(getattr(event, "vars_used", []) or []) | set(getattr(event, "vars_defined", []) or [])
    if not referenced:
        return diff_dict

    def keep(kind: str, path: str, payload: Any) -> bool:
        var_name = extract_var_name(path)
        return var_name in referenced

    return _filter_by_predicate(diff_dict, keep)

def filter_based_on_used_vars(diff_dict: Dict[str, Any], event) -> Dict[str, Any]:
    """Keep entries whose var is in event.vars_used."""
    used = set(getattr(event, "vars_used", []) or [])
    if not used:
        return {}

    def keep(kind: str, path: str, payload: Any) -> bool:
        var_name = extract_var_name(path)
        return var_name in used

    return _filter_by_predicate(diff_dict, keep)

def filter_based_on_type_changes(diff_dict: Dict[str, Any], event) -> Dict[str, Any]:
    """
    Last resort: if >1 changes remain and 'type_changes' exists, keep ONLY 'type_changes'.
    Otherwise return input unchanged.
    """
    if count_changed_vars(diff_dict) > 1 and "type_changes" in diff_dict:
        return {"type_changes": diff_dict["type_changes"]}
    return diff_dict

def apply_trace_filters(diffs_by_kind: Dict[str, Any], event) -> Dict[str, Any]:
    """
    Pipeline:
      1) filter_added_dict_based_on_seen_variables
      2) if empty OR <=1 change -> return
      3) filter_based_on_vars_at_current_line
      4) if <=1 change -> return
      5) filter_based_on_used_vars
      6) last-resort: type_changes only if still >1 changes and key exists
    Always returns a dict (possibly empty).
    Focus is LineEvent; if event lacks expected fields, gracefully degrades to {}.
    """
    if not diffs_by_kind:
        return {}

    # Step 1
    step1 = filter_added_dict_based_on_seen_variables(diffs_by_kind, event)
    n1 = count_changed_vars(step1)
    if n1 <= 1:
        return step1 or {}

    # Step 3
    step3 = filter_based_on_vars_at_current_line(step1, event)
    n3 = count_changed_vars(step3)
    if n3 <= 1:
        return step3 or {}

    # Step 5
    step5 = filter_based_on_used_vars(step3, event)
    n5 = count_changed_vars(step5)
    if n5 <= 1:
        return step5 or {}

    return filter_based_on_type_changes(step5, event)