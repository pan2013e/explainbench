"""Load every shared resource from the installed wheel."""

from __future__ import annotations

from conftest import CleanWheel


def test_clean_resources(clean_wheel: CleanWheel):
    result = clean_wheel.run_python(
        """
from explainbench.resources import load_shared_intent_artifacts
from explainbench.submission import supported_instance_ids

instance_ids = supported_instance_ids()
assert len(instance_ids) == 297
for task in ("e2e.intent", "local.intent"):
    artifacts = load_shared_intent_artifacts(task)
    assert artifacts.instance_ids == instance_ids
    assert set(artifacts.context) == instance_ids
    assert set(artifacts.ground_truths) == instance_ids
print("clean resources passed")
"""
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "clean resources passed"
