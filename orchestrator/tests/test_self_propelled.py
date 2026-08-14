"""Tests for self-propelled development orchestration."""

from uuid import uuid4

import pytest

from app.config import settings
from app.models import ProjectState
from app.services.self_propelled import (
    get_iteration,
    get_self_propelled_meta,
    is_self_propelled_enabled,
    set_self_propelled_enabled,
    should_continue_iterating,
)
from app.workspace.manager import WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    return WorkspaceManager(str(tmp_path))


def test_default_self_propelled_enabled(workspace):
    project_id = uuid4()
    meta = workspace.load_metadata(project_id)
    assert is_self_propelled_enabled(meta) is True
    assert get_iteration(meta) == 0


def test_disable_self_propelled(workspace):
    project_id = uuid4()
    sp = set_self_propelled_enabled(workspace, project_id, False)
    assert sp["enabled"] is False
    meta = workspace.load_metadata(project_id)
    assert is_self_propelled_enabled(meta) is False


def test_should_continue_respects_max_iterations(workspace):
    project_id = uuid4()
    meta = workspace.load_metadata(project_id)
    sp = get_self_propelled_meta(meta)
    sp["iteration"] = settings.max_self_propelled_iterations
    meta["self_propelled"] = sp
    workspace.save_metadata(project_id, meta)

    can, reason = should_continue_iterating(meta, ProjectState.REVIEW)
    assert can is False
    assert reason == "max_iterations"


def test_should_stop_in_production(workspace):
    meta = {}
    can, reason = should_continue_iterating(meta, ProjectState.PRODUCTION)
    assert can is False
    assert reason == "production"
