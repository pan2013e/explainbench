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
SOURCE_BUILD_STEP2_SHA256 = (
    "1e1015229ae4704d29aab3e2e586c499f6c6a24a1ffd4aba5c4974d555c1aa62"
)
SOURCE_INFER_EXPRESSION_SHA256 = (
    "33289a327da7f5ea4bdacc453e85339510c11c4ba177400c5abccfe7f1904205"
)
SOURCE_EVALUATION_INFERENCE_SHA256 = (
    "f0be57ea07363b4b3b54b6ef2f52ba16bf7fb5850106b776c3b28412023bf8b6"
)
DATASET_EFFECT_TARGET = Path(
    "src/core/dataset/extract_ground_truths/effect"
)
DATASET_EFFECT_SOURCE = Path("dataset/extract_ground_truths/effect")
ADDED_DATASET_EFFECT_FILES = {
    Path("audit_files.py"),
    Path("paid_inference.py"),
}
ADAPTED_DATASET_EFFECT_FILES = {
    Path("build_step2.py"),
    Path("infer_expression.py"),
}
ADAPTED_COPIED_TREE_FILES = {
    Path("src/core/evaluation"): {Path("inference.py")},
}

COPIED_TREES = {
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
    target_root = PACKAGE_ROOT / DATASET_EFFECT_TARGET
    source_root = SOURCE_ROOT / DATASET_EFFECT_SOURCE
    target_files = files_below(target_root)
    source_files = files_below(source_root)

    assert target_files - ADDED_DATASET_EFFECT_FILES == source_files
    for relative_path in sorted(
        source_files - ADAPTED_DATASET_EFFECT_FILES
    ):
        assert file_digest(target_root / relative_path) == file_digest(
            source_root / relative_path
        )

    for target_relative, source_relative in COPIED_TREES.items():
        target_root = PACKAGE_ROOT / target_relative
        source_root = SOURCE_ROOT / source_relative
        target_files = files_below(target_root)
        source_files = files_below(source_root)

        assert target_files == source_files
        adapted = ADAPTED_COPIED_TREE_FILES.get(target_relative, set())
        for relative_path in sorted(target_files - adapted):
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


def test_paid_inference_adapters_are_recorded():
    target_root = PACKAGE_ROOT / DATASET_EFFECT_TARGET
    build_step2 = target_root / "build_step2.py"
    infer_expression = target_root / "infer_expression.py"

    assert file_digest(build_step2) != SOURCE_BUILD_STEP2_SHA256
    assert file_digest(infer_expression) != SOURCE_INFER_EXPRESSION_SHA256
    assert "PaidInferenceJournal" in build_step2.read_text(encoding="utf-8")
    assert "raw_response_callback" in infer_expression.read_text(
        encoding="utf-8"
    )
    for relative_path in ADDED_DATASET_EFFECT_FILES:
        assert (target_root / relative_path).is_file()

    evaluation_inference = (
        PACKAGE_ROOT / "src/core/evaluation/inference.py"
    )
    assert (
        file_digest(evaluation_inference)
        != SOURCE_EVALUATION_INFERENCE_SHA256
    )
    assert "InferencePersistenceError" in evaluation_inference.read_text(
        encoding="utf-8"
    )
