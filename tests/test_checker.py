import json

from explainbench.checker import check_submission
from explainbench.cli import main


INSTANCE_ID = "astropy__astropy-12907"


def write_json(tmp_path, data):
    path = tmp_path / "submission.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_checker_summary_counts_only_nonempty_patches(tmp_path):
    path = write_json(
        tmp_path,
        {
            "submission_id": "test-agent",
            "instances": [
                {
                    "instance_id": INSTANCE_ID,
                    "explanation": "explanation",
                    "model_patch": "",
                }
            ],
        },
    )

    summary = check_submission(path)

    assert summary.submission_id == "test-agent"
    assert summary.instance_count == 1
    assert summary.explanation_count == 1
    assert summary.patch_count == 0


def test_checker_cli_prints_success_summary(tmp_path, capsys):
    path = write_json(
        tmp_path,
        {
            "submission_id": "test-agent",
            "instances": [
                {
                    "instance_id": INSTANCE_ID,
                    "explanation": "explanation",
                }
            ],
        },
    )

    status = main(["checker", str(path)])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    assert captured.out == (
        "Submission is valid\n"
        "Submission ID: test-agent\n"
        "Instances: 1\n"
        "Explanations: 1\n"
        "Patches: 0\n"
    )


def test_checker_cli_prints_all_validation_errors_to_stderr(tmp_path, capsys):
    path = write_json(
        tmp_path,
        {
            "submission_id": "test-agent",
            "instances": [
                {
                    "instance_id": "unknown__project-1",
                    "explanation": "explanation",
                    "model_patch": "not a patch",
                }
            ],
        },
    )

    status = main(["checker", str(path)])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert captured.err.startswith("Submission is invalid\n")
    assert "instances[0].instance_id" in captured.err
    assert "instances[0].model_patch" in captured.err


def test_checker_cli_reports_missing_file(tmp_path, capsys):
    status = main(["checker", str(tmp_path / "missing.json")])

    captured = capsys.readouterr()
    assert status == 1
    assert "cannot read" in captured.err
