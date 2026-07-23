"""Run and resume the first canonical builder stage from the installed wheel."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import CleanWheel


INSTANCE_ID = "sympy__sympy-15349"
PATCH = """\
diff --git a/module.py b/module.py
--- a/module.py
+++ b/module.py
@@ -1,2 +1,2 @@
 def changed():
-    return 1
+    return 2
"""


def _assert_success(result, label: str) -> None:
    assert result.returncode == 0, (
        f"{label} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_clean_local_builder(clean_wheel: CleanWheel):
    stage_result = clean_wheel.run(
        [
            str(clean_wheel.executable),
            "question-builder",
            "local",
            "stages",
        ]
    )
    _assert_success(stage_result, "stage listing")
    stage_lines = [
        line for line in stage_result.stdout.splitlines() if line.strip()
    ]
    assert len(stage_lines) == 10
    assert "identify-patched-functions" in stage_lines[0]

    root = clean_wheel.run_directory / "local-builder"
    repository_cache = root / "repositories"
    repository = repository_cache / INSTANCE_ID / "owner" / "repository"
    repository.mkdir(parents=True)

    for arguments in (
        ["git", "init"],
        ["git", "config", "user.email", "clean-wheel@example.invalid"],
        ["git", "config", "user.name", "Clean Wheel"],
    ):
        result = clean_wheel.run(arguments, cwd=repository)
        _assert_success(result, "Git repository setup")

    (repository / "module.py").write_text(
        "def changed():\n    return 1\n",
        encoding="utf-8",
    )
    _assert_success(
        clean_wheel.run(["git", "add", "module.py"], cwd=repository),
        "Git add",
    )
    _assert_success(
        clean_wheel.run(
            ["git", "commit", "-m", "Create test repository"],
            cwd=repository,
        ),
        "Git commit",
    )
    revision_result = clean_wheel.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
    )
    _assert_success(revision_result, "Git revision")
    revision = revision_result.stdout.strip()

    dataset = root / "dataset.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "instance_id": INSTANCE_ID,
                    "repo": "owner/repository",
                    "base_commit": revision,
                    "patch": PATCH,
                }
            ]
        ),
        encoding="utf-8",
    )
    submission = root / "submission.json"
    submission.write_text(
        json.dumps(
            {
                "submission_id": "clean-wheel-agent",
                "instances": [
                    {
                        "instance_id": INSTANCE_ID,
                        "explanation": "The return value changed.",
                        "model_patch": PATCH,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    workspace = root / "workspace"
    command = [
        str(clean_wheel.executable),
        "question-builder",
        "local",
        "stage",
        "identify-patched-functions",
        str(submission),
        "--workspace",
        str(workspace),
        "--repository-cache",
        str(repository_cache),
        "--dataset-name",
        str(dataset),
        "--repository-remote",
        "https://example.invalid",
        "--max-attempts",
        "1",
    ]

    initial = clean_wheel.run(command)
    _assert_success(initial, "initial identify stage")
    assert "completed=1" in initial.stdout

    resumed = clean_wheel.run([*command, "--resume"])
    _assert_success(resumed, "resumed identify stage")
    assert "reused=1" in resumed.stdout

    instance_root = (
        workspace
        / "stages"
        / "identify-patched-functions"
        / "instances"
        / INSTANCE_ID
    )
    status = json.loads(
        (instance_root / "status.json").read_text(encoding="utf-8")
    )
    result = json.loads(
        (instance_root / "result.json").read_text(encoding="utf-8")
    )
    command_records = list((instance_root / "work").rglob("command.json"))

    assert status["state"] == "completed"
    assert status["total_attempts"] == 1
    assert result["data"]["qualnames"] == ["module:changed"]
    assert len(command_records) == 1

    import_result = clean_wheel.run_python(
        """
import dataset
import execution
import tracer

for package in (dataset, execution, tracer):
    assert "site-packages" in package.__file__
print("clean local builder passed")
"""
    )
    _assert_success(import_result, "installed core imports")
    assert import_result.stdout.strip() == "clean local builder passed"
