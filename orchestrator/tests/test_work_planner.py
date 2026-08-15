from app.services.work_planner import optimize_work_units, plan_parallel_work, work_plan_to_dict


def test_default_parallel_streams():
    units = plan_parallel_work([], "A web app with API and UI")
    streams = [u.stream for u in units]
    assert streams == ["backend", "frontend", "feature", "feature"]
    feature_ids = [u.feature_id for u in units if u.stream == "feature"]
    assert "ux-polish" in feature_ids
    assert "core-completeness" in feature_ids


def test_feature_notes_spawn_parallel_agents():
    notes = [
        {"type": "feature", "content": "Export to CSV"},
        {"type": "feature", "content": "Email notifications"},
        {"type": "instruction", "content": "Keep it simple"},
    ]
    units = plan_parallel_work(notes, "Task manager")
    streams = [u.stream for u in units]
    assert streams.count("backend") == 1
    assert streams.count("frontend") == 1
    assert streams.count("feature") == 4
    feature_units = [u for u in units if u.stream == "feature" and u.feature_content and "CSV" in u.feature_content]
    assert len(feature_units) == 1
    assert feature_units[0].feature_id


def test_api_only_skips_frontend():
    units = plan_parallel_work([], "Headless API only service, no UI")
    assert [u.stream for u in units] == ["backend"]


def test_work_plan_serializable():
    units = plan_parallel_work([{"type": "feature", "content": "Dark mode"}], "App")
    plan = work_plan_to_dict(units)
    assert len(plan["units"]) == 5
    assert plan["units"][0]["stream"] == "backend"


def test_optimize_work_units_batches_many_features():
    notes = [{"type": "feature", "content": f"Feature {i}"} for i in range(8)]
    units = plan_parallel_work(notes, "Big app")
    optimized = optimize_work_units(units, max_parallel=2)
    assert len(optimized) <= 4
    assert any(u.stream == "backend" for u in optimized)
    assert any(u.stream == "frontend" for u in optimized)
