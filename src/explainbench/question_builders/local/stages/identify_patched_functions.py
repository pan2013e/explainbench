"""Identify Python functions touched by a submitted unified diff."""

from __future__ import annotations

import ast
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from pydantic import Field

from explainbench.question_builders.common.orchestration import (
    StageContext,
    StageExecutionError,
    StageResult,
)
from explainbench.question_builders.common.status import StoredStageResult
from explainbench.schemas import StrictModel


class ModifiedFunctionsResult(StrictModel):
    """Qualified function names found in old and patched source."""

    repository: str
    base_commit: str
    old_functions: list[str] = Field(default_factory=list)
    new_functions: list[str] = Field(default_factory=list)
    patched_functions: list[str] = Field(default_factory=list)


class _QualnameVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.definitions: list[tuple[int, int, str]] = []

    def _enter(self, node: ast.AST, name: str) -> None:
        self.stack.append(name)
        decorators = getattr(node, "decorator_list", ())
        start = decorators[0].lineno if decorators else node.lineno
        end = getattr(node, "end_lineno", start)
        self.definitions.append((start, end, ".".join(self.stack)))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_function(node, "<lambda>")

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
        name: str,
    ) -> None:
        self._enter(node, name)
        self.stack.append("<locals>")
        children = [node.body] if isinstance(node, ast.Lambda) else node.body
        for child in children:
            self.visit(child)
        self.stack.pop()
        self.stack.pop()
        for field_name, child in ast.iter_fields(node):
            if field_name == "body":
                continue
            if isinstance(child, ast.AST):
                self.visit(child)
            elif isinstance(child, list):
                for item in child:
                    if isinstance(item, ast.AST):
                        self.visit(item)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name)
        self.generic_visit(node)
        self.stack.pop()


_FILE_HEADER = re.compile(r"--- (?:a/)?(.*?)\n\+\+\+ (?:b/)?(.*?)\n")
_HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*?)\n")


def extract_modified_lines(patch: str) -> dict[str, dict[str, list[int]]]:
    """Return added and removed source line numbers grouped by file."""

    added: dict[str, list[int]] = defaultdict(list)
    removed: dict[str, list[int]] = defaultdict(list)
    for file_patch in patch.split("diff --git ")[1:]:
        header = _FILE_HEADER.search(file_patch)
        if header is None:
            continue
        old_path, new_path = header.groups()
        hunks = list(_HUNK_HEADER.finditer(file_patch))
        split_parts = _HUNK_HEADER.split(file_patch)[1:]
        for index, hunk in enumerate(hunks):
            old_line = int(hunk.group(1))
            new_line = int(hunk.group(2))
            body_index = index * 4 + 3
            if body_index >= len(split_parts):
                continue
            for line in split_parts[body_index].splitlines():
                if line.startswith("-"):
                    removed[old_path].append(old_line)
                    old_line += 1
                elif line.startswith("+"):
                    added[new_path].append(new_line)
                    new_line += 1
                elif line.startswith(" "):
                    old_line += 1
                    new_line += 1

    return {
        "added": {
            path: sorted(set(lines)) for path, lines in added.items() if lines
        },
        "removed": {
            path: sorted(set(lines)) for path, lines in removed.items() if lines
        },
    }


def path_to_module_name(file_path: str | Path) -> str:
    """Convert a repository-relative Python path to its import-style name."""

    parts = list(Path(file_path).parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[0] in {"lib", "src"}:
        parts = parts[1:]
    return ".".join(part for part in parts if part) or "<unknown_module>"


def _qualname_for_line(
    definitions: list[tuple[int, int, str]],
    line_number: int,
) -> str | None:
    candidates = [
        item for item in definitions if item[0] <= line_number <= item[1]
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[2]


def extract_modified_qualnames(
    patch: str,
    repository_root: str | Path,
    *,
    version: str,
) -> list[str]:
    """Extract qualified names containing removed or added patch lines."""

    if version not in {"old", "new"}:
        raise ValueError("version must be 'old' or 'new'")
    line_groups = extract_modified_lines(patch)
    selected = line_groups["removed" if version == "old" else "added"]
    root = Path(repository_root)
    qualified_names: set[str] = set()
    for relative_path, line_numbers in selected.items():
        if relative_path == "/dev/null" or not relative_path.endswith(".py"):
            continue
        source_path = root / relative_path
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
        visitor = _QualnameVisitor()
        visitor.visit(tree)
        module_name = path_to_module_name(relative_path)
        for line_number in line_numbers:
            local_name = _qualname_for_line(visitor.definitions, line_number)
            if local_name is not None:
                qualified_names.add(f"{module_name}:{local_name}")
    return sorted(qualified_names)


@dataclass(frozen=True)
class RepositoryCheckout:
    root: Path
    repository: str
    base_commit: str


class RepositoryProvider(Protocol):
    def prepare(self, context: StageContext) -> RepositoryCheckout:
        ...

    def apply_patch(self, checkout: RepositoryCheckout, patch: str) -> None:
        ...


def _run_git(arguments: list[str], **kwargs) -> None:
    subprocess.run(arguments, check=True, **kwargs)


class GitRepositoryProvider:
    """Prepare an isolated per-instance checkout using SWE-bench metadata."""

    def __init__(
        self,
        *,
        dataset_loader: Callable[..., list[Mapping[str, Any]]] | None = None,
    ) -> None:
        self._dataset_loader = dataset_loader

    def _load_instance(self, context: StageContext) -> Mapping[str, Any]:
        loader = self._dataset_loader
        if loader is None:
            from swebench.harness.utils import load_swebench_dataset

            loader = load_swebench_dataset
        records = loader(
            name=context.config.benchmark_dataset,
            split=context.config.benchmark_split,
            instance_ids=[context.instance.instance_id],
        )
        if len(records) != 1:
            raise ValueError(
                f"expected one benchmark record, received {len(records)}"
            )
        return records[0]

    def prepare(self, context: StageContext) -> RepositoryCheckout:
        record = self._load_instance(context)
        repository = str(record["repo"])
        base_commit = str(record["base_commit"])
        checkout_root = context.work_directory / "repository"
        if (checkout_root / ".git").is_dir():
            _run_git(["git", "-C", str(checkout_root), "reset", "--hard", "HEAD"])
            _run_git(["git", "-C", str(checkout_root), "clean", "-fdx"])
        else:
            remote = context.config.repository_remote.rstrip("/")
            _run_git(
                [
                    "git",
                    "clone",
                    f"{remote}/{repository}.git",
                    str(checkout_root),
                ]
            )
        _run_git(["git", "-C", str(checkout_root), "checkout", base_commit])
        return RepositoryCheckout(checkout_root, repository, base_commit)

    def apply_patch(self, checkout: RepositoryCheckout, patch: str) -> None:
        _run_git(
            [
                "git",
                "-C",
                str(checkout.root),
                "apply",
                "--whitespace=nowarn",
                "-",
            ],
            input=patch.encode("utf-8"),
        )


class IdentifyPatchedFunctionsRunner:
    """Stage runner for old/new patched-function discovery."""

    def __init__(self, provider: RepositoryProvider | None = None) -> None:
        self.provider = provider or GitRepositoryProvider()

    def run_instance(self, context: StageContext) -> StageResult:
        patch = context.instance.model_patch
        if patch is None or not patch.strip():
            raise StageExecutionError(
                "submission instance has no patch",
                category="invalid_submission_patch",
            )
        try:
            checkout = self.provider.prepare(context)
            old_functions = extract_modified_qualnames(
                patch,
                checkout.root,
                version="old",
            )
            self.provider.apply_patch(checkout, patch)
            new_functions = extract_modified_qualnames(
                patch,
                checkout.root,
                version="new",
            )
        except subprocess.CalledProcessError as error:
            raise StageExecutionError(
                f"repository preparation or patch application failed: {error}",
                category="repository_command_failed",
                retryable=True,
            ) from error
        except (OSError, SyntaxError, ValueError) as error:
            raise StageExecutionError(
                f"could not identify patched functions: {error}",
                category="patched_function_analysis_failed",
                retryable=False,
            ) from error
        output = ModifiedFunctionsResult(
            repository=checkout.repository,
            base_commit=checkout.base_commit,
            old_functions=old_functions,
            new_functions=new_functions,
            patched_functions=sorted(set(old_functions) | set(new_functions)),
        )
        return StageResult.completed(output.model_dump(mode="json"))

    def validate_result(self, result: StoredStageResult) -> None:
        ModifiedFunctionsResult.model_validate(result.data)
