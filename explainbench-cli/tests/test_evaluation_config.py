import pytest

from explainbench.evaluation.config import (
    DEFAULT_EVALUATOR_MODEL,
    EvaluationConfigError,
    load_evaluation_config,
    resolve_evaluation_config,
)
from explainbench.evaluation.registry import TaskName


def write_config(tmp_path, content):
    path = tmp_path / "evaluation.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_config_resolves_relative_paths_and_cli_overrides(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=test\n", encoding="utf-8")
    path = write_config(
        tmp_path,
        """\
schema_version = 1

[selection]
mode = "full"

[evaluator]
model = "configured-model"
num_generations = 4
instance_workers = 3
generation_workers = 2
temperature = 0.4
top_p = 0.8
max_tokens = 2048
max_retries = 7

[paths]
output = "outputs/results.json"
artifacts_dir = "question-artifacts"

[environment]
env_file = ".env"
""",
    )

    file_config, source = load_evaluation_config(path)
    resolved = resolve_evaluation_config(
        file_config,
        source=source,
        num_generations=1,
        temperature=0.2,
    )

    assert resolved.selection.mode.value == "full"
    assert resolved.evaluator.model == "configured-model"
    assert resolved.evaluator.num_generations == 1
    assert resolved.evaluator.instance_workers == 3
    assert resolved.evaluator.generation_workers == 2
    assert resolved.evaluator.temperature == 0.2
    assert resolved.evaluator.top_p == 0.8
    assert resolved.evaluator.max_tokens == 2048
    assert resolved.evaluator.max_retries == 7
    assert resolved.output == (tmp_path / "outputs/results.json").resolve()
    assert resolved.artifacts_dir == (tmp_path / "question-artifacts").resolve()
    assert resolved.env_file == env_file.resolve()


def test_cli_task_selection_replaces_configured_mode(tmp_path):
    path = write_config(
        tmp_path,
        """\
schema_version = 1
[selection]
mode = "full"
[paths]
output = "results.json"
""",
    )
    file_config, source = load_evaluation_config(path)

    resolved = resolve_evaluation_config(
        file_config,
        source=source,
        tasks=["local.intent", "e2e.effect"],
    )

    assert resolved.selection.mode is None
    assert resolved.selection.tasks == (
        TaskName.LOCAL_INTENT,
        TaskName.E2E_EFFECT,
    )


def test_config_uses_package_defaults_for_omitted_evaluator_values(tmp_path):
    path = write_config(
        tmp_path,
        """\
schema_version = 1
[selection]
mode = "lite"
[paths]
output = "results.json"
""",
    )
    file_config, source = load_evaluation_config(path)

    resolved = resolve_evaluation_config(file_config, source=source)

    assert resolved.evaluator.model == DEFAULT_EVALUATOR_MODEL
    assert resolved.evaluator.num_generations == 5
    assert resolved.evaluator.instance_workers == 10
    assert resolved.evaluator.generation_workers == 10
    assert resolved.evaluator.temperature == 1.0
    assert resolved.evaluator.top_p == 1.0
    assert resolved.evaluator.max_tokens == 8192
    assert resolved.evaluator.max_retries == 5


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            """\
schema_version = 1
unknown = true
""",
            "Extra inputs are not permitted",
        ),
        (
            """\
schema_version = 1
[selection]
mode = "lite"
tasks = ["local.intent"]
""",
            "mutually exclusive",
        ),
        (
            """\
schema_version = 1
[evaluator]
num_generations = "five"
""",
            "valid integer",
        ),
    ],
)
def test_config_rejects_unknown_conflicting_and_mistyped_values(
    tmp_path,
    content,
    message,
):
    path = write_config(tmp_path, content)

    with pytest.raises(EvaluationConfigError, match=message):
        load_evaluation_config(path)


def test_resolver_requires_selection_and_output():
    with pytest.raises(EvaluationConfigError, match="select one --mode"):
        resolve_evaluation_config(output="result.json")

    with pytest.raises(EvaluationConfigError, match="output path is required"):
        resolve_evaluation_config(mode="lite")


def test_resolver_rejects_missing_environment_file(tmp_path):
    with pytest.raises(EvaluationConfigError, match="does not exist"):
        resolve_evaluation_config(
            mode="lite",
            output="result.json",
            env_file=tmp_path / "missing.env",
        )
