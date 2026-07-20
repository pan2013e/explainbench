import difflib
from pathlib import Path

from explainbench.question_builders.common.orchestration import StageContext
from explainbench.question_builders.local.stages.identify_patched_functions import (
    IdentifyPatchedFunctionsRunner,
    RepositoryCheckout,
    extract_modified_lines,
    extract_modified_qualnames,
    path_to_module_name,
)
from explainbench.schemas import SubmissionInstance


OLD_SOURCE = """\
value = 1

class Example:
    @staticmethod
    def outer(value):
        def inner():
            return value
        return inner()
"""

NEW_SOURCE = """\
value = 2

class Example:
    @staticmethod
    def outer(value):
        def inner():
            return value + 1
        return inner()
"""


def make_patch():
    body = "".join(
        difflib.unified_diff(
            OLD_SOURCE.splitlines(keepends=True),
            NEW_SOURCE.splitlines(keepends=True),
            fromfile="a/src/package/example.py",
            tofile="b/src/package/example.py",
        )
    )
    return f"diff --git a/src/package/example.py b/src/package/example.py\n{body}"


class FakeRepositoryProvider:
    def __init__(self, root: Path):
        self.root = root

    def prepare(self, context):
        source = self.root / "src" / "package" / "example.py"
        source.parent.mkdir(parents=True)
        source.write_text(OLD_SOURCE, encoding="utf-8")
        return RepositoryCheckout(
            root=self.root,
            repository="owner/project",
            base_commit="abc123",
        )

    def apply_patch(self, checkout, patch):
        (checkout.root / "src" / "package" / "example.py").write_text(
            NEW_SOURCE,
            encoding="utf-8",
        )


class Config:
    benchmark_dataset = "fixture.json"
    benchmark_split = "test"
    repository_remote = "https://example.invalid"


def test_extract_modified_lines_matches_old_and_new_line_numbers():
    result = extract_modified_lines(make_patch())

    assert result == {
        "added": {"src/package/example.py": [1, 7]},
        "removed": {"src/package/example.py": [1, 7]},
    }


def test_extract_modified_qualnames_uses_innermost_definition(tmp_path):
    source = tmp_path / "src" / "package" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_text(OLD_SOURCE, encoding="utf-8")

    result = extract_modified_qualnames(
        make_patch(),
        tmp_path,
        version="old",
    )

    assert result == [
        "package.example:Example.outer.<locals>.inner",
    ]


def test_path_to_module_name_strips_only_source_layout_prefix():
    assert path_to_module_name("src/package/example.py") == "package.example"
    assert path_to_module_name("lib/module.py") == "module"
    assert path_to_module_name("package/tests/test_example.py") == (
        "package.tests.test_example"
    )


def test_stage_runner_combines_old_and_new_functions(tmp_path):
    runner = IdentifyPatchedFunctionsRunner(
        FakeRepositoryProvider(tmp_path / "repository")
    )
    context = StageContext(
        instance=SubmissionInstance(
            instance_id="owner__project-1",
            explanation="Explanation",
            model_patch=make_patch(),
        ),
        workspace=tmp_path,
        work_directory=tmp_path / "work",
        log_directory=tmp_path / "logs",
        upstream_results={},
        config=Config(),
    )

    result = runner.run_instance(context).to_stored()
    runner.validate_result(result)

    assert result.data == {
        "repository": "owner/project",
        "base_commit": "abc123",
        "old_functions": [
            "package.example:Example.outer.<locals>.inner",
        ],
        "new_functions": [
            "package.example:Example.outer.<locals>.inner",
        ],
        "patched_functions": [
            "package.example:Example.outer.<locals>.inner",
        ],
    }

