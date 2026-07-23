"""Check that copied core files still match the extraction source."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PACKAGE_ROOT.parent
SOURCE_EXECUTION_UTIL_SHA256 = (
    "3e2a4335c087b15e66545c5ac0b1809429171f36292d80540deb0ab4f8bee14e"
)

COPIED_TREES = {
    Path("src/core/dataset/extract_ground_truths/effect"): Path(
        "dataset/extract_ground_truths/effect"
    ),
    Path("src/core/evaluation"): Path("evaluation"),
    Path("src/core/tracer"): Path("py-tracer/tracer"),
    Path("src/core/tracer_plugin"): Path("py-tracer/tracer_plugin"),
}

COPIED_FILES = {
    Path("src/core/dataset/__init__.py"): Path("dataset/__init__.py"),
    Path("src/core/dataset/extract_ground_truths/__init__.py"): Path(
        "dataset/extract_ground_truths/__init__.py"
    ),
    Path("src/core/execution/__init__.py"): Path("execution/__init__.py"),
    Path("src/core/execution/allowed_functions.json"): Path(
        "execution/allowed_functions.json"
    ),
    Path("src/core/execution/allowed_qualnames.json"): Path(
        "execution/allowed_qualnames.json"
    ),
    Path("src/core/execution/inspect.py"): Path("execution/inspect.py"),
    Path("src/core/execution/trace.py"): Path("execution/trace.py"),
    Path("src/core/execution/track.py"): Path("execution/track.py"),
    Path("src/core/execution/monkey_patch/__init__.py"): Path(
        "execution/monkey_patch/__init__.py"
    ),
    Path("src/core/execution/monkey_patch/inspect.py"): Path(
        "execution/monkey_patch/inspect.py"
    ),
    Path("src/core/execution/monkey_patch/trace.py"): Path(
        "execution/monkey_patch/trace.py"
    ),
    Path("src/core/execution/monkey_patch/track.py"): Path(
        "execution/monkey_patch/track.py"
    ),
}


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_below(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }


@pytest.mark.skipif(
    not (SOURCE_ROOT / "dataset").is_dir(),
    reason="requires the research repository during extraction",
)
def test_copied_core_files_match_research_source():
    for target_relative, source_relative in COPIED_TREES.items():
        target_root = PACKAGE_ROOT / target_relative
        source_root = SOURCE_ROOT / source_relative
        target_files = files_below(target_root)
        source_files = files_below(source_root)

        assert target_files == source_files
        for relative_path in sorted(target_files):
            assert file_digest(target_root / relative_path) == file_digest(
                source_root / relative_path
            )

    for target_relative, source_relative in COPIED_FILES.items():
        assert file_digest(PACKAGE_ROOT / target_relative) == file_digest(
            SOURCE_ROOT / source_relative
        )


def test_execution_packaging_adapter_is_recorded():
    target = PACKAGE_ROOT / "src/core/execution/util.py"

    assert file_digest(target) != SOURCE_EXECUTION_UTIL_SHA256
    target_text = target.read_text(encoding="utf-8")
    assert "find_spec" in target_text
    assert "_package_directory" in target_text
