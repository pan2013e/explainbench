import tarfile

from execution import util


def test_prepare_tracer_builds_installable_payload(tmp_path, monkeypatch):
    archive = tmp_path / "py-tracer.tar"
    monkeypatch.setattr(util, "get_tmp_tracer_path", lambda: str(archive))

    util.prepare_tracer()

    with tarfile.open(archive, "r") as payload:
        names = set(payload.getnames())
        project = payload.extractfile("py-tracer/pyproject.toml")
        assert project is not None
        project_text = project.read().decode("utf-8")

    assert "py-tracer/tracer/__init__.py" in names
    assert "py-tracer/tracer_plugin/__init__.py" in names
    assert "py-tracer/tracer_plugin/pytest_plugin.py" in names
    assert "tracer_plugin = \"tracer_plugin.pytest_plugin\"" in project_text
    assert not any("__pycache__" in name for name in names)
    assert not any(name.endswith((".pyc", ".pyo")) for name in names)
