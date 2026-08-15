from pathlib import Path

from app.services.completed_work import filter_units_for_feedback, work_unit_key
from app.services.work_planner import WorkUnit, plan_parallel_work
from app.workspace.manager import WorkspaceManager


def test_work_unit_key_uses_feature_id():
    unit = WorkUnit(stream="feature", title="X", description="Y", feature_id="export-csv")
    assert work_unit_key(unit) == "export-csv"


def test_filter_skips_completed_features(monkeypatch, tmp_path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(ws_root))
    monkeypatch.setattr("app.config.settings.workspace_root", str(ws_root))
    ws = WorkspaceManager()
    project_id = __import__("uuid").uuid4()
    repo = ws.repo_dir(project_id)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "app").mkdir()
    (repo / "app" / "main.py").write_text("print('x')" * 50, encoding="utf-8")
    (repo / "app" / "static").mkdir()
    (repo / "app" / "static" / "index.html").write_text("<html></html>", encoding="utf-8")

    notes = [{"type": "feature", "content": "Export to CSV"}]
    units = plan_parallel_work(notes, "Web app")
    completed = {"backend", "frontend", "ux-polish", "core-completeness", "export-to-csv"}
    filtered = filter_units_for_feedback(units, completed=completed, repo=repo)
    assert filtered == []
