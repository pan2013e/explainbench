"""Select detailed-tracing functions from lightweight call-stack records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from pydantic import Field

from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
    StageResult,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.question_builders.local.stages.identify_patched_functions import (
    ModifiedFunctionsResult,
)
from explainbench.schemas import StrictModel


class TrackedCallArtifacts(StrictModel):
    """Trace-file locations produced by lightweight call tracking."""

    buggy_trace_files: list[str] = Field(min_length=1)
    patched_trace_files: list[str] = Field(min_length=1)


class TraceFunctionsResult(StrictModel):
    """Functions selected for detailed state tracing."""

    target_functions: list[str]
    trace_functions: list[str]
    buggy_trace_files: list[str]
    patched_trace_files: list[str]


def load_json_lines(path: str | Path) -> Iterable[dict[str, Any]]:
    """Yield validated JSON objects from one call-tracking JSONL file."""

    source = Path(path)
    with source.open("r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{source}:{line_number} is not valid JSON: {error.msg}"
                ) from error
            if not isinstance(value, dict):
                raise ValueError(
                    f"{source}:{line_number} must contain a JSON object"
                )
            yield value


def collect_trace_functions(
    trace_files: Iterable[str | Path],
    target_functions: Iterable[str],
) -> list[str]:
    """Collect the union of stack qualnames observed for selected targets."""

    targets = set(target_functions)
    functions: set[str] = set()
    for trace_file in trace_files:
        for entry in load_json_lines(trace_file):
            if entry.get("target") not in targets:
                continue
            stack = entry.get("stack") or []
            if not isinstance(stack, list):
                raise ValueError(f"{trace_file} contains a non-list stack")
            for frame in stack:
                if not isinstance(frame, (list, tuple)) or len(frame) < 2:
                    continue
                qualname = frame[1]
                if isinstance(qualname, str) and qualname:
                    functions.add(qualname)
    return sorted(functions)


def _workspace_paths(workspace: Path, values: list[str]) -> list[Path]:
    paths = []
    for value in values:
        path = Path(value)
        if not path.is_absolute():
            path = workspace / path
        paths.append(path)
    return paths


class SelectTraceFunctionsRunner:
    """Build the detailed trace whitelist from tracked buggy/patched calls."""

    def run_instance(self, context: StageContext) -> StageResult:
        try:
            modified = ModifiedFunctionsResult.model_validate(
                context.upstream_results["identify-patched-functions"].data
            )
            tracked = TrackedCallArtifacts.model_validate(
                context.upstream_results["track-test-calls"].data
            )
            trace_files = _workspace_paths(
                context.workspace,
                tracked.buggy_trace_files + tracked.patched_trace_files,
            )
            missing = [str(path) for path in trace_files if not path.is_file()]
            if missing:
                raise OSError(
                    "tracked call files are missing: " + ", ".join(missing[:3])
                )
            functions = collect_trace_functions(
                trace_files,
                modified.patched_functions,
            )
        except (KeyError, OSError, ValueError) as error:
            raise StageExecutionError(
                f"could not select trace functions: {error}",
                category="tracked_calls_invalid",
                retryable=isinstance(error, OSError),
            ) from error
        output = TraceFunctionsResult(
            target_functions=modified.patched_functions,
            trace_functions=functions,
            buggy_trace_files=tracked.buggy_trace_files,
            patched_trace_files=tracked.patched_trace_files,
        )
        return StageResult.completed(output.model_dump(mode="json"))

    def validate_result(self, result: StoredStageResult) -> None:
        TraceFunctionsResult.model_validate(result.data)

