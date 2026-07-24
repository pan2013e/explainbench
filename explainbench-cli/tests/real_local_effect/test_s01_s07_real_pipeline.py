"""Opt-in real SWE-bench tests for local-effect scenarios S01 through S07."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from explainbench.question_builders.common.artifacts import (
    resolve_artifact_root,
)
from explainbench.question_builders.common.atomic_files import atomic_write_json
from explainbench.question_builders.local.workspace import LocalBuilderWorkspace
from explainbench.submission import ValidationProfile, load_submission


ROOT = Path(__file__).resolve().parents[2]
SUBMISSION_PATH = ROOT / "examples" / "submission-full.json"
INSTANCE_ID = "sympy__sympy-15349"
RUN_ENVIRONMENT_VARIABLE = "EXPLAINBENCH_RUN_REAL_LOCAL_EFFECT"
STAGES = (
    "identify-patched-functions",
    "track-test-calls",
    "select-trace-functions",
    "trace-program-state",
    "find-first-divergence",
    "generate-candidate-expressions",
)


pytestmark = [
    pytest.mark.real_local_effect,
    pytest.mark.skipif(
        os.environ.get(RUN_ENVIRONMENT_VARIABLE) != "1",
        reason=(
            f"set {RUN_ENVIRONMENT_VARIABLE}=1 to run real local-effect tests"
        ),
    ),
]


@dataclass(frozen=True)
class RealLocalEffectCase:
    """Fixed paths and executable for one inspectable real-data test run."""

    executable: str
    workspace: Path
    evidence_path: Path
    command_timeout_seconds: int


@pytest.fixture(scope="session")
def real_case() -> RealLocalEffectCase:
    executable = os.environ.get("EXPLAINBENCH_REAL_EXECUTABLE")
    if executable is None:
        active_executable = Path(sys.executable).with_name("explainbench")
        if active_executable.is_file():
            executable = str(active_executable)
        else:
            executable = shutil.which("explainbench")
    if executable is None:
        pytest.fail(
            "the explainbench executable is unavailable; install the package "
            "or set EXPLAINBENCH_REAL_EXECUTABLE"
        )

    configured_workspace = os.environ.get("EXPLAINBENCH_REAL_WORKSPACE")
    workspace = (
        Path(configured_workspace).expanduser()
        if configured_workspace
        else ROOT / ".explainbench" / "real-tests" / "sympy-15349"
    )
    workspace = workspace.resolve()
    timeout = int(
        os.environ.get("EXPLAINBENCH_REAL_COMMAND_TIMEOUT_SECONDS", "50000")
    )
    if timeout < 1:
        pytest.fail("EXPLAINBENCH_REAL_COMMAND_TIMEOUT_SECONDS must be positive")
    return RealLocalEffectCase(
        executable=executable,
        workspace=workspace,
        evidence_path=workspace.parent / f"{workspace.name}-evidence.json",
        command_timeout_seconds=timeout,
    )


def _record_command(
    case: RealLocalEffectCase,
    *,
    scenario: str,
    command: list[str],
    started_at: str,
    duration_seconds: float,
    result: subprocess.CompletedProcess[str],
) -> None:
    try:
        payload = json.loads(case.evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = {
            "schema_version": 1,
            "submission": str(SUBMISSION_PATH),
            "instance_id": INSTANCE_ID,
            "workspace": str(case.workspace),
            "commands": [],
        }
    payload["commands"].append(
        {
            "scenario": scenario,
            "command": command,
            "started_at": started_at,
            "duration_seconds": round(duration_seconds, 3),
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )
    atomic_write_json(case.evidence_path, payload)


def _run_cli(
    case: RealLocalEffectCase,
    scenario: str,
    arguments: list[str],
) -> subprocess.CompletedProcess[str]:
    command = [case.executable, *arguments]
    print(f"\n[{scenario}] {shlex.join(command)}", flush=True)
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=case.command_timeout_seconds,
        check=False,
    )
    _record_command(
        case,
        scenario=scenario,
        command=command,
        started_at=started_at,
        duration_seconds=time.monotonic() - started,
        result=result,
    )
    assert result.returncode == 0, (
        f"{scenario} failed with exit status {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result


def _stage_arguments(case: RealLocalEffectCase, stage: str) -> list[str]:
    arguments = [
        "question-builder",
        "local",
        "stage",
        stage,
        str(SUBMISSION_PATH),
        "--workspace",
        str(case.workspace),
        "--resume",
    ]
    if stage == "generate-candidate-expressions":
        arguments.append("--no-candidate-inference")
    return arguments


def _ensure_through(
    case: RealLocalEffectCase,
    scenario: str,
    target_stage: str,
) -> subprocess.CompletedProcess[str]:
    target_index = STAGES.index(target_stage)
    result = None
    for stage in STAGES[: target_index + 1]:
        result = _run_cli(
            case,
            f"{scenario}:{stage}",
            _stage_arguments(case, stage),
        )
    assert result is not None
    return result


def _workspace(case: RealLocalEffectCase) -> LocalBuilderWorkspace:
    return LocalBuilderWorkspace.inspect(case.workspace)


def _assert_trace_artifacts(
    workspace: LocalBuilderWorkspace,
    stage: str,
) -> None:
    result = workspace.read_result(stage, INSTANCE_ID)
    workspace.validate_result_artifacts(stage, INSTANCE_ID, result)
    instance_directory = (
        workspace.root / "stages" / stage / "instances" / INSTANCE_ID
    )
    manifest, root = resolve_artifact_root(
        result.data["artifact_manifest"],
        relative_to=instance_directory,
    )
    assert manifest.files
    assert any(item.path.startswith("buggy_traces/") for item in manifest.files)
    assert any(
        item.path.startswith("patched_traces/") for item in manifest.files
    )
    assert all(item.size > 0 for item in manifest.files)
    assert root.is_dir()


def test_s01_validates_real_submission(real_case: RealLocalEffectCase) -> None:
    result = _run_cli(
        real_case,
        "S01",
        ["checker", str(SUBMISSION_PATH)],
    )
    submission = load_submission(
        SUBMISSION_PATH,
        profile=ValidationProfile.QUESTION_BUILDER_LOCAL,
    )

    assert submission.submission_id == "example-full"
    assert len(submission.instances) == 1
    assert submission.instances[0].instance_id == INSTANCE_ID
    assert submission.instances[0].model_patch
    assert "valid" in result.stdout.lower()


def test_s02_identifies_patch_and_reuses_checkpoint(
    real_case: RealLocalEffectCase,
) -> None:
    _ensure_through(real_case, "S02", "identify-patched-functions")
    workspace = _workspace(real_case)
    result = workspace.read_result("identify-patched-functions", INSTANCE_ID)

    assert result.outcome == "completed"
    assert any(
        "to_rotation_matrix" in qualname
        for qualname in result.data["qualnames"]
    )

    resumed = _run_cli(
        real_case,
        "S02:resume",
        _stage_arguments(real_case, "identify-patched-functions"),
    )
    assert "reused=1" in resumed.stdout


def test_s03_tracks_real_test_calls_and_reuses_artifacts(
    real_case: RealLocalEffectCase,
) -> None:
    _ensure_through(real_case, "S03", "track-test-calls")
    workspace = _workspace(real_case)
    _assert_trace_artifacts(workspace, "track-test-calls")

    resumed = _run_cli(
        real_case,
        "S03:resume",
        _stage_arguments(real_case, "track-test-calls"),
    )
    assert "reused=1" in resumed.stdout


def test_s04_selects_relevant_trace_functions(
    real_case: RealLocalEffectCase,
) -> None:
    _ensure_through(real_case, "S04", "select-trace-functions")
    result = _workspace(real_case).read_result(
        "select-trace-functions",
        INSTANCE_ID,
    )
    functions = result.data["functions"]

    assert result.outcome == "completed"
    assert functions
    assert any("to_rotation_matrix" in function for function in functions)


def test_s05_records_real_detailed_traces(
    real_case: RealLocalEffectCase,
) -> None:
    _ensure_through(real_case, "S05", "trace-program-state")
    _assert_trace_artifacts(_workspace(real_case), "trace-program-state")


def test_s06_finds_real_quaternion_divergence(
    real_case: RealLocalEffectCase,
) -> None:
    _ensure_through(real_case, "S06", "find-first-divergence")
    result = _workspace(real_case).read_result(
        "find-first-divergence",
        INSTANCE_ID,
    )
    divergence = result.data["divergence"]

    assert result.outcome == "completed"
    assert divergence
    assert "to_rotation_matrix" in divergence["function_name"]
    assert divergence["file_path"].endswith("sympy/algebras/quaternion.py")
    assert divergence["before_or_after"] in {"before", "after"}


def test_s07_prepares_candidate_metadata_without_model_inference(
    real_case: RealLocalEffectCase,
) -> None:
    _ensure_through(
        real_case,
        "S07",
        "generate-candidate-expressions",
    )
    result = _workspace(real_case).read_result(
        "generate-candidate-expressions",
        INSTANCE_ID,
    )
    candidates = result.data["candidates"]

    assert result.outcome == "completed"
    assert result.data["inference"] is False
    assert candidates["prompt_length_chars"] > 0
    assert "changed_candidates" not in candidates
    assert "unchanged_candidates" not in candidates
