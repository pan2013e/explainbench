import re
from typing import Iterable, Optional, Set, Dict, Callable, Any, Iterator, Tuple, MutableMapping
from collections.abc import Sequence

BASE_IGNORE_FIELDS: Set[str] = {"vars_used", "vars_defined"}
# If there is a new repo and field that should be ignored, we can easily ignore the ordering by adding
# "<reponame>": {"<target_field_name>"}
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

def filter_based_on_type_changes(diff_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Last resort: if >1 changes remain and 'type_changes' exists, keep ONLY 'type_changes'.
    Otherwise return input unchanged.
    """
    if count_changed_vars(diff_dict) > 1 and "type_changes" in diff_dict:
        return {"type_changes": diff_dict["type_changes"]}
    return diff_dict

def filter_docstring_changes(diff_dict: Dict[str, Any]) ->Dict[str, Any]:
    """
    Filter the docstring changes using heuristics number of words
    """
    MAX_WORDS = 50
    for change_key, change_val in diff_dict.items():
        if isinstance(change_val, dict) and change_key == "values_changed":
            for full_path, values_dict in change_val.items():
                if (isinstance(values_dict, dict) and 
                    isinstance(values_dict.get("new_value", None), str) and 
                    isinstance(values_dict.get("old_value", None), str) and
                    (len(values_dict["new_value"].split()) > MAX_WORDS or len(values_dict["old_value"].split()) > MAX_WORDS)):
                        del change_val[full_path]
    return diff_dict

def extract_attribute_name(full_path: str) -> str:
    tokens = _BRACKETED_NAME_RE.findall(str(full_path))
    return tokens[-1]

def filter_hash_attribute(diff_dict: Dict[str, Any]) -> Dict[str, Any]:
    def keep(kind: str, path: str, payload: Any) -> bool:
        return extract_attribute_name(path) != "_hash"
    return _filter_by_predicate(diff_dict, keep)

def filter_perinstance(diffs_by_kind: Dict[str, Any], instance_id: str) -> Dict[str, Any]:
    if instance_id == "astropy__astropy-7336":
        return filter_hash_attribute(diffs_by_kind)
    return diffs_by_kind

def apply_trace_filters(diffs_by_kind: Dict[str, Any], event, instance_id: str) -> Dict[str, Any]:
    """
    Pipeline (early-exits when <=1 change remains):
      0) instance-specific tweaks
      1) omit/trim docstring 'values_changed' entries via heuristic
      2) filter_added_dict_based_on_seen_variables
      3) filter_based_on_vars_at_current_line
      4) filter_based_on_used_vars
      5) last-resort: type_changes only (if still >1)
    Always returns a dict (possibly empty).
    """
    if not diffs_by_kind:
        return {}

    # Step 0: per-instance
    cur = filter_perinstance(diffs_by_kind, instance_id)

    # Step 1: docstring-specific trimming (returns {} if nothing applicable)
    cur = filter_docstring_changes(cur)

    # Step 2
    cur = filter_added_dict_based_on_seen_variables(cur, event)
    if count_changed_vars(cur) <= 1:
        return cur or {}

    # Step 3
    cur = filter_based_on_vars_at_current_line(cur, event)
    if count_changed_vars(cur) <= 1:
        return cur or {}

    # Step 4
    cur = filter_based_on_used_vars(cur, event)
    if count_changed_vars(cur) <= 1:
        return cur or {}

    # Step 5
    return filter_based_on_type_changes(cur)

# EXCLUSION_RULES: Dict[str, Dict[str, Set[str]]] = {
#     "astropy__astropy-14182": {
#         "astropy.table.connect.TableRead": {"__doc__", "description"}
#     },
# }

# def make_excluder() -> Callable[[str, Dict[str, Any]], Dict[str, Any]]:
#     def _recursive_clean(data: Any) -> None:
#         """
#         Recursively traverse `data` and delete attributes according to `EXCLUSION_RULES`.
#         """
#         if isinstance(data, MutableMapping):
#             # Check if this dict represents an object or function
#             obj_name = data.get("py/object") or data.get("py/function")
#             if isinstance(obj_name, str) and obj_name in EXCLUSION_RULES:
#                 for attr in EXCLUSION_RULES[obj_name]:
#                     if attr in data:
#                         del data[attr]

#             # Continue recursion for nested structures
#             for value in list(data.values()):
#                 if isinstance(value, (MutableMapping, list)):
#                     _recursive_clean(value)

#         elif isinstance(data, list):
#             for item in data:
#                 if isinstance(item, (MutableMapping, list)):
#                     _recursive_clean(item)

#     def excluder(instance_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
#         """
#         Apply exclusion rules for a specific instance.
#         """
#         if instance_id not in EXCLUSION_RULES:
#             return data
#         _recursive_clean(data)
#         return data

#     return excluder

