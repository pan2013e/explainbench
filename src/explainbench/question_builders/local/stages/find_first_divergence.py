"""Find the first useful behavioral divergence in stored detailed traces."""

from __future__ import annotations

import json
import mmap
import os
import random
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

import deepdiff
from deepdiff import DeepDiff
from pydantic import Field

from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
    StageResult,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.schemas import StrictModel


RANDOMIZED_FUNCTIONS = {
    "django.contrib.auth.base_user:AbstractBaseUser.set_password",
    "django.core.cache.backends.base:BaseCache.get_backend_timeout",
    "sphinx.util.logging:SphinxLoggerAdapter.log",
    "sphinx.environment:BuildEnvironment.__getstate__",
    "__init__:SphinxTransform.env",
    "tests.utils:create_server.<locals>.server",
    "xarray.tests:create_test_data",
}
WRAPPER_FUNCTIONS = {
    "sympy.multipledispatch.dispatcher:Dispatcher.__call__",
    "sympy.core.cache:__cacheit.<locals>.func_wrapper.<locals>.wrapper",
}
IGNORE_ORDER_FIELDS = {
    "astropy": {"attr_names", "frame_names", "unit", "_all_units"},
    "django": {"_property_names"},
}


class TracePair(StrictModel):
    """One buggy/patched detailed trace pair and its patch line metadata."""

    test_id: int = Field(ge=0)
    buggy_trace_file: str
    patched_trace_file: str
    removed_lines: dict[str, list[int]] = Field(default_factory=dict)
    added_lines: dict[str, list[int]] = Field(default_factory=dict)


class DetailedTraceArtifacts(StrictModel):
    """Detailed execution artifacts produced by trace-program-state."""

    trace_pairs: list[TracePair] = Field(min_length=1)


class DivergenceResult(StrictModel):
    """Agent-specific divergence or an explicit semantic fallback marker."""

    outcome: Literal["agent_divergence", "gold_fallback"]
    metadata: dict[str, Any] | None = None
    fallback_reason: str | None = None


def _load_events(path: Path) -> list[Any]:
    from tracer.protocol import Event

    with path.open("rb") as trace_file:
        if os.fstat(trace_file.fileno()).st_size == 0:
            raise ValueError(f"trace file is empty: {path}")
        memory = mmap.mmap(trace_file.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            events = []
            while line := memory.readline():
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"trace file contains invalid JSON: {path}: {error}"
                    ) from error
                events.append(Event.from_dict(payload))
            return events
        finally:
            memory.close()


def _values_equal(first: Any, second: Any) -> bool:
    return DeepDiff(
        first,
        second,
        significant_digits=5,
        ignore_private_variables=False,
    ) == {}


class _FunctionBlock:
    def __init__(
        self,
        event_id: int,
        name: str,
        parent: "_FunctionBlock | None",
        *,
        parameters: Any = None,
        patch_modified: bool = False,
    ) -> None:
        self.event_id = event_id
        self.name = name
        self.parent = parent
        self.parameters = parameters
        self.patch_modified = patch_modified
        self.return_value = None
        self.exception = None
        self.events: list[Any] = []
        self.links: dict[int, _FunctionBlock] = {}
        self.index = -1

    def add_event(self, event: Any) -> None:
        self.events.append(event)

    def step_into(self, event: Any) -> "_FunctionBlock":
        return self.links[event.event_id]

    @cached_property
    def return_event(self) -> Any:
        if self.exception is None:
            if not self.events or self.events[-1].event_type != "Return":
                raise ValueError(f"function {self.name!r} has no return event")
            return self.events[-1]
        if len(self.events) < 2 or self.events[-2].event_type != "Exception":
            raise ValueError(f"function {self.name!r} has no exception event")
        return self.events[-2]

    @cached_property
    def return_type(self) -> str:
        return self.return_event.event_type

    @cached_property
    def depth(self) -> int:
        return 0 if self.parent is None else self.parent.depth + 1

    def __iter__(self):
        return self

    def __next__(self) -> Any:
        if self.index == -1:
            if self.patch_modified:
                self.index = len(self.events) - (2 if self.exception else 1)
            else:
                self.index = 0
        while self.index < len(self.events):
            event = self.events[self.index]
            self.index += 1
            if not (
                getattr(event, "excluded", False)
                and event.event_type == "Line"
            ):
                return event
        raise StopIteration


class _Traces:
    def __init__(self, path: Path, diff_lines: Mapping[str, list[int]]) -> None:
        self.entry_block = _FunctionBlock(-1, "<module>", None)
        self.events = _load_events(path)
        self.diff_lines = diff_lines
        self.patch_modified_functions = self._find_patch_modified_functions()
        self._build()

    def _find_patch_modified_functions(self) -> set[str]:
        functions = set()
        for event in self.events:
            relative = os.path.relpath(event.filepath, "/testbed")
            if event.line_number in self.diff_lines.get(relative, []):
                functions.add(event.function_name)
        return functions

    def _build(self) -> None:
        stack = [self.entry_block]
        for index, event in enumerate(self.events):
            stack[-1].add_event(event)
            relative = os.path.relpath(event.filepath, "/testbed")
            if event.line_number in self.diff_lines.get(relative, []):
                event.excluded = True
            if event.event_type == "Function":
                block = _FunctionBlock(
                    event.event_id,
                    event.function_name,
                    stack[-1],
                    parameters=event.parameters,
                    patch_modified=(
                        event.function_name in self.patch_modified_functions
                    ),
                )
                stack[-1].links[event.event_id] = block
                stack.append(block)
            elif event.event_type == "Return":
                stack[-1].return_value = event.return_value
                if (
                    stack[-1].return_value is not None
                    and stack[-1].exception is not None
                    and stack[-1].exception[0] == "StopIteration"
                ):
                    stack[-1].exception = None
                stack.pop()
            elif event.event_type == "Exception":
                next_event = (
                    self.events[index + 1]
                    if index + 1 < len(self.events)
                    else None
                )
                if next_event is not None and next_event.event_type == "Return":
                    stack[-1].exception = (
                        event.exception_type,
                        event.exception_value,
                    )

    @property
    def entry(self) -> _FunctionBlock:
        blocks = list(self.entry_block.links.values())
        if not blocks:
            raise ValueError("trace does not call a test function")
        return blocks[0]


def _ignore_order_function(repository_name: str):
    ignored = {"vars_used", "vars_defined"}
    ignored.update(IGNORE_ORDER_FIELDS.get(repository_name, set()))

    def should_ignore(level) -> bool:
        values = (getattr(level, "t1", None), getattr(level, "t2", None))
        if not any(
            isinstance(value, (list, tuple)) and not isinstance(value, str)
            for value in values
        ):
            return False
        segments = level.path(output_format="list")
        last_name = next(
            (item for item in reversed(segments) if isinstance(item, str)),
            None,
        )
        return last_name in ignored

    return should_ignore


def _diff_events(buggy: Any, patched: Any, repository_name: str) -> Any:
    return DeepDiff(
        buggy.dump(),
        patched.dump(),
        cache_size=5000,
        significant_digits=3,
        ignore_order=False,
        ignore_order_func=_ignore_order_function(repository_name),
        ignore_private_variables=False,
    )


def path_depth(path: str) -> int:
    segments = re.findall(r"\[(.*?)\]", path)
    if not segments:
        return 0
    cleaned = [
        segment[1:-1]
        if len(segment) >= 2
        and segment[0] == segment[-1]
        and segment[0] in {"'", '"'}
        else segment
        for segment in (item.strip() for item in segments)
    ]
    if cleaned[0] in {
        "return_value",
        "exception_type",
        "exception_value",
        "seen_variables",
    }:
        return len(cleaned) - 1
    return len(cleaned)


def _depth_filter(diff: Mapping[str, Any], threshold: int) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    for change_kind, entries in diff.items():
        if isinstance(entries, (list, deepdiff.helper.SetOrdered)):
            selected = [item for item in entries if path_depth(item) <= threshold]
            if selected:
                filtered[change_kind] = selected
        elif isinstance(entries, dict):
            selected = {
                path: payload
                for path, payload in entries.items()
                if path_depth(path) <= threshold
            }
            if selected:
                filtered[change_kind] = selected
        else:
            raise TypeError(
                f"unsupported diff entry type for {change_kind}: {type(entries)}"
            )
    return filtered


def _shallowest_diff(diff: Mapping[str, Any], rng: random.Random) -> dict[str, Any]:
    candidates = []
    for change_kind, entries in diff.items():
        if isinstance(entries, (list, deepdiff.helper.SetOrdered)):
            candidates.extend(
                (path_depth(path), change_kind, "list", path, None)
                for path in entries
            )
        elif isinstance(entries, dict):
            candidates.extend(
                (path_depth(path), change_kind, "dict", path, payload)
                for path, payload in entries.items()
            )
        else:
            raise TypeError(
                f"unsupported diff entry type for {change_kind}: {type(entries)}"
            )
    if not candidates:
        return {}
    minimum = min(item[0] for item in candidates)
    _, change_kind, kind, path, payload = rng.choice(
        [item for item in candidates if item[0] == minimum]
    )
    if kind == "list":
        return {change_kind: [path]}
    return {change_kind: {path: payload}}


_BRACKETED_NAME = re.compile(r"\[['\"]([^'\"]+)['\"]\]")


def _variable_views(event: Any, diff: Mapping[str, Any]) -> dict[str, Any]:
    if event.event_type == "Line":
        output = {}
        for entries in diff.values():
            paths = entries.keys() if isinstance(entries, dict) else entries
            for path in paths:
                names = _BRACKETED_NAME.findall(str(path))
                if len(names) > 1 and names[1] in event.seen_variables:
                    output[names[1]] = event.seen_variables[names[1]]
        return output
    if event.event_type in {"Exception", "Return"}:
        if event.event_type == "Exception":
            return {
                "__exception__": [event.exception_type, event.exception_value]
            }
        return {"__return__": event.return_value}
    return {}


def _event_count(event: Any, traces: _Traces) -> int:
    count = 0
    for candidate in traces.events:
        if (
            candidate.line_number == event.line_number
            and candidate.filepath == event.filepath
            and candidate.function_name == event.function_name
            and candidate.event_type != "Function"
        ):
            count += 1
        if candidate is event:
            break
    return count


def _state_diff(
    buggy_event: Any,
    patched_event: Any,
    *,
    repository_name: str,
    depth_threshold: int,
    use_depth_filter: bool,
    rng: random.Random,
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    diff = _diff_events(buggy_event, patched_event, repository_name)
    if use_depth_filter:
        diff = _depth_filter(diff, depth_threshold)
    selected = _shallowest_diff(diff, rng)
    if not selected:
        return None
    location = (
        "The return statement in the provided function"
        if buggy_event.event_type in {"Exception", "Return"}
        else buggy_event.statement
    )
    before_or_after = (
        "after"
        if "Exception" in {buggy_event.event_type, patched_event.event_type}
        or "Return" in {buggy_event.event_type, patched_event.event_type}
        else "before"
    )
    return {
        "file_path": patched_event.filepath,
        "buggy_event_id": buggy_event.event_id,
        "patched_event_id": patched_event.event_id,
        "buggy_event_type": buggy_event.event_type,
        "patched_event_type": patched_event.event_type,
        "buggy_statement": buggy_event.statement,
        "patched_statement": patched_event.statement,
        "location": location,
        "before_or_after": before_or_after,
        "buggy_lineno": buggy_event.line_number,
        "patched_lineno": patched_event.line_number,
        "diff": selected,
        "buggy_variables": _variable_views(buggy_event, selected),
        "patched_variables": _variable_views(patched_event, selected),
        **metadata,
    }


def find_first_divergence(
    *,
    buggy_trace: Path,
    patched_trace: Path,
    removed_lines: Mapping[str, list[int]],
    added_lines: Mapping[str, list[int]],
    instance_id: str,
    submission_id: str,
    test_id: int,
    depth_threshold: int,
    random_seed: int,
) -> dict[str, Any]:
    """Compare one valid trace pair using the legacy traversal semantics."""

    repository_name = instance_id.split("__", 1)[0]
    buggy_traces = _Traces(buggy_trace, removed_lines)
    patched_traces = _Traces(patched_trace, added_lines)
    buggy_function = buggy_traces.entry
    patched_function = patched_traces.entry
    patch_modified_exists = bool(
        buggy_traces.patch_modified_functions
        and patched_traces.patch_modified_functions
    )
    diffing_started = not patch_modified_exists
    rng = random.Random(random_seed)

    while True:
        try:
            buggy_event = next(buggy_function)
            patched_event = next(patched_function)
        except StopIteration:
            if buggy_function.parent and patched_function.parent:
                buggy_function = buggy_function.parent
                patched_function = patched_function.parent
                continue
            return {}

        if not diffing_started and (
            buggy_function.patch_modified or patched_function.patch_modified
        ):
            diffing_started = True
        if (
            buggy_function.name == patched_function.name
            and buggy_event.matches(patched_event)
        ):
            if buggy_event.event_type == "Function":
                buggy_callee = buggy_function.step_into(buggy_event)
                patched_callee = patched_function.step_into(patched_event)
                if not diffing_started and (
                    buggy_callee.patch_modified
                    or patched_callee.patch_modified
                    or buggy_callee.name in WRAPPER_FUNCTIONS
                ):
                    diffing_started = True
                if (
                    buggy_callee.name not in RANDOMIZED_FUNCTIONS
                    and buggy_callee.name not in WRAPPER_FUNCTIONS
                ):
                    if buggy_callee.patch_modified:
                        if (
                            "Exception"
                            not in {
                                buggy_callee.return_type,
                                patched_callee.return_type,
                            }
                            and buggy_function.depth > 1
                        ):
                            continue
                    buggy_function = buggy_callee
                    patched_function = patched_callee
                continue
            if not diffing_started:
                continue
            divergence = _state_diff(
                buggy_event,
                patched_event,
                repository_name=repository_name,
                depth_threshold=depth_threshold,
                use_depth_filter=submission_id == "gold",
                rng=rng,
                metadata={
                    "test_id": test_id,
                    "function_name": buggy_function.name,
                    "buggy_line_count": _event_count(
                        buggy_event, buggy_traces
                    ),
                    "patched_line_count": _event_count(
                        patched_event, patched_traces
                    ),
                    "buggy_function_param": buggy_function.parameters,
                    "instance_id": instance_id,
                    "submission_id": submission_id,
                    "seen_patched_function": patch_modified_exists,
                },
            )
            if divergence:
                buggy_names = set(divergence["buggy_variables"])
                patched_names = set(divergence["patched_variables"])
                parameter_names = (
                    set(buggy_function.parameters)
                    if isinstance(buggy_function.parameters, dict)
                    else set()
                ) | (
                    set(patched_function.parameters)
                    if isinstance(patched_function.parameters, dict)
                    else set()
                )
                intersection = (buggy_names | patched_names) & parameter_names
                if intersection and all(
                    _values_equal(
                        divergence["buggy_variables"].get(name),
                        buggy_function.parameters.get(name),
                    )
                    and _values_equal(
                        divergence["patched_variables"].get(name),
                        patched_function.parameters.get(name),
                    )
                    for name in intersection
                ):
                    if buggy_function.parent and patched_function.parent:
                        buggy_function = buggy_function.parent
                        patched_function = patched_function.parent
                        continue
                    return {}
                return divergence
        else:
            diffing_started = True
            buggy_return = buggy_function.return_event
            patched_return = patched_function.return_event
            divergence = _state_diff(
                buggy_return,
                patched_return,
                repository_name=repository_name,
                depth_threshold=depth_threshold,
                use_depth_filter=submission_id == "gold",
                rng=rng,
                metadata={
                    "test_id": test_id,
                    "function_name": buggy_function.name,
                    "buggy_line_count": _event_count(
                        buggy_return, buggy_traces
                    ),
                    "patched_line_count": _event_count(
                        patched_return, patched_traces
                    ),
                    "buggy_function_param": buggy_function.parameters,
                    "instance_id": instance_id,
                    "submission_id": submission_id,
                    "seen_patched_function": patch_modified_exists,
                },
            )
            if divergence:
                return divergence
            if buggy_function.parent and patched_function.parent:
                buggy_function = buggy_function.parent
                patched_function = patched_function.parent
                continue
            return {}


def _type_stub(value: Any) -> Any:
    if isinstance(value, dict):
        keys = [key for key in value if not key.startswith("py/")]
        if "py/object" in value and keys:
            return {"py/object": value["py/object"], "__dir__": keys}
        if "py/type" in value and keys:
            return value
        return {"py/object": "builtins.dict"}
    if isinstance(value, list):
        return {"py/object": "builtins.list", "len": len(value)}
    raise ValueError(f"cannot simplify value of type {type(value).__name__}")


def simplify_value(value: Any, max_depth: int, depth: int = 0) -> Any:
    if isinstance(value, dict):
        if depth > max_depth:
            return _type_stub(value)
        return {
            key: simplify_value(child, max_depth, depth + 1)
            for key, child in value.items()
        }
    if isinstance(value, list):
        if depth > max_depth:
            return _type_stub(value)
        return [
            simplify_value(child, max_depth, depth + 1) for child in value
        ]
    return value


DivergenceFinder = Callable[..., dict[str, Any]]


class FindFirstDivergenceRunner:
    """Try valid trace pairs and preserve semantic fallback explicitly."""

    def __init__(self, finder: DivergenceFinder = find_first_divergence) -> None:
        self.finder = finder

    def run_instance(self, context: StageContext) -> StageResult:
        try:
            artifacts = DetailedTraceArtifacts.model_validate(
                context.upstream_results["trace-program-state"].data
            )
        except (KeyError, ValueError) as error:
            raise StageExecutionError(
                f"detailed trace metadata is invalid: {error}",
                category="detailed_trace_metadata_invalid",
            ) from error

        valid_pairs = 0
        pair_errors = []
        for pair in artifacts.trace_pairs:
            buggy_path = Path(pair.buggy_trace_file)
            patched_path = Path(pair.patched_trace_file)
            if not buggy_path.is_absolute():
                buggy_path = context.workspace / buggy_path
            if not patched_path.is_absolute():
                patched_path = context.workspace / patched_path
            if not buggy_path.is_file() or not patched_path.is_file():
                pair_errors.append(f"test {pair.test_id}: trace file is missing")
                continue
            try:
                divergence = self.finder(
                    buggy_trace=buggy_path,
                    patched_trace=patched_path,
                    removed_lines=pair.removed_lines,
                    added_lines=pair.added_lines,
                    instance_id=context.instance.instance_id,
                    submission_id=context.submission_id or "unknown",
                    test_id=pair.test_id,
                    depth_threshold=context.config.divergence_depth,
                    random_seed=context.config.random_seed,
                )
                valid_pairs += 1
            except (AssertionError, IndexError, OSError, ValueError) as error:
                pair_errors.append(f"test {pair.test_id}: {error}")
                continue
            if divergence:
                for key in ("buggy_variables", "patched_variables"):
                    if key in divergence:
                        divergence[key] = simplify_value(
                            divergence[key],
                            context.config.variable_max_depth,
                        )
                if "buggy_function_param" in divergence:
                    divergence["buggy_function_param"] = simplify_value(
                        divergence["buggy_function_param"],
                        context.config.parameter_max_depth,
                    )
                output = DivergenceResult(
                    outcome="agent_divergence",
                    metadata=divergence,
                )
                return StageResult.completed(output.model_dump(mode="json"))

        if valid_pairs == 0:
            raise StageExecutionError(
                "no valid detailed trace pair could be read: "
                + "; ".join(pair_errors),
                category="detailed_traces_unusable",
                retryable=True,
            )
        output = DivergenceResult(
            outcome="gold_fallback",
            fallback_reason="no_usable_agent_divergence",
        )
        return StageResult.completed(output.model_dump(mode="json"))

    def validate_result(self, result: StoredStageResult) -> None:
        DivergenceResult.model_validate(result.data)
