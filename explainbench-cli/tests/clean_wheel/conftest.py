"""Shared isolated wheel installation for clean-wheel tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class CleanWheel:
    root: Path
    run_directory: Path
    python: Path
    executable: Path
    environment: dict[str, str]
    source_root: Path

    def run(
        self,
        arguments: list[str],
        *,
        cwd: Path | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            arguments,
            cwd=cwd or self.run_directory,
            env=self.environment,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_python(
        self,
        script: str,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        return self.run([str(self.python), "-c", script, *arguments])


def _run_setup(
    arguments: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> None:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"clean-wheel setup failed: {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


@pytest.fixture(scope="session")
def clean_wheel(tmp_path_factory: pytest.TempPathFactory) -> CleanWheel:
    source_root = Path(__file__).resolve().parents[2]
    uv = shutil.which("uv")
    if uv is None:
        pytest.fail("clean-wheel tests require the uv executable")

    root = tmp_path_factory.mktemp("clean-wheel")
    distribution_directory = root / "distribution"
    environment_directory = root / "environment"
    run_directory = root / "run"
    cache_directory = root / "uv-cache"
    distribution_directory.mkdir()
    run_directory.mkdir()
    cache_directory.mkdir()

    setup_environment = os.environ.copy()
    setup_environment["UV_CACHE_DIR"] = str(cache_directory)
    setup_environment.pop("PYTHONPATH", None)

    _run_setup(
        [
            uv,
            "build",
            "--wheel",
            "--out-dir",
            str(distribution_directory),
            str(source_root),
        ],
        cwd=root,
        environment=setup_environment,
    )
    wheels = list(distribution_directory.glob("*.whl"))
    if len(wheels) != 1:
        pytest.fail(f"expected one wheel, found {len(wheels)}")

    _run_setup(
        [
            uv,
            "venv",
            "--python",
            "3.12",
            str(environment_directory),
        ],
        cwd=root,
        environment=setup_environment,
    )
    python = environment_directory / "bin" / "python"
    executable = environment_directory / "bin" / "explainbench"
    _run_setup(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            str(wheels[0]),
        ],
        cwd=root,
        environment=setup_environment,
    )

    command_environment = os.environ.copy()
    command_environment.pop("PYTHONPATH", None)
    command_environment["PYTHONNOUSERSITE"] = "1"
    command_environment["PATH"] = (
        f"{environment_directory / 'bin'}{os.pathsep}"
        f"{command_environment.get('PATH', '')}"
    )

    try:
        yield CleanWheel(
            root=root,
            run_directory=run_directory,
            python=python,
            executable=executable,
            environment=command_environment,
            source_root=source_root,
        )
    finally:
        shutil.rmtree(source_root / "build", ignore_errors=True)
        shutil.rmtree(source_root / "explainbench.egg-info", ignore_errors=True)
