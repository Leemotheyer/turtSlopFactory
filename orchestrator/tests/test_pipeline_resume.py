from uuid import uuid4

import pytest

from app.pipeline.executor import PipelineExecutor, _STAGE_UNIT_TESTING
from app.models import ProjectState


def test_load_failed_gate_does_not_skip_implementation_on_unit_test_failure():
    executor = PipelineExecutor()
    project_id = uuid4()
    context: dict = {}
    executor.workspace.save_metadata(
        project_id,
        {
            "failed_gate": ProjectState.IMPLEMENTING.value,
            "failed_substage": _STAGE_UNIT_TESTING,
        },
    )

    gate = executor._load_failed_gate(project_id, context)

    assert gate == ProjectState.IMPLEMENTING
    assert context.get("failed_substage") == _STAGE_UNIT_TESTING
    assert "implementation_complete" not in context


def test_persist_last_failure_roundtrip():
    executor = PipelineExecutor()
    project_id = uuid4()
    context = {"last_failure": "pytest FAILED: assert 404 == 200"}

    executor._persist_last_failure(project_id, context)
    meta = executor.workspace.load_metadata(project_id)

    assert "pytest FAILED" in meta["last_failure"]
