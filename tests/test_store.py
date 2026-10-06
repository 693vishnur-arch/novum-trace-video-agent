import json

import pytest

from backend.app.services import store


def test_failed_replace_leaves_previous_state_readable(tmp_path, monkeypatch):
    project = tmp_path / "job"
    project.mkdir()
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.save_state(project, {"status": "queued"})
    def fail(*args):
        raise OSError("disk error")
    monkeypatch.setattr(type(project), "replace", fail)
    with pytest.raises(OSError):
        store.save_state(project, {"status": "complete"})
    assert store.load_state("job")["status"] == "queued"
    assert json.loads((project / "project.json").read_text())["status"] == "queued"
