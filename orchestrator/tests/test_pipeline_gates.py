from app.models import ProjectState
from app.state_machine import (
    PIPELINE_GATES,
    advance_project,
    fail_project,
    normalize_pipeline_gate,
    pipeline_gate_index,
)


def test_pipeline_gate_order():
    assert PIPELINE_GATES[0] == ProjectState.PLANNING
    assert PIPELINE_GATES[-1] == ProjectState.REVIEW


def test_pipeline_gate_index():
    assert pipeline_gate_index(ProjectState.PLANNING) == 0
    assert pipeline_gate_index(ProjectState.IMPLEMENTING) == 1
    assert pipeline_gate_index(ProjectState.REVIEW) == 7
    assert pipeline_gate_index(ProjectState.DIAGNOSING) is None


def test_normalize_diagnosing_uses_failed_gate():
    gate = normalize_pipeline_gate(ProjectState.DIAGNOSING, ProjectState.UNIT_TESTING)
    assert gate == ProjectState.UNIT_TESTING


def test_normalize_diagnosing_defaults_to_implementing():
    gate = normalize_pipeline_gate(ProjectState.FIXING, None)
    assert gate == ProjectState.IMPLEMENTING


def test_normalize_blocked_uses_failed_gate():
    gate = normalize_pipeline_gate(
        ProjectState.AUTONOMOUSLY_BLOCKED,
        ProjectState.DOCKER_BUILD,
    )
    assert gate == ProjectState.DOCKER_BUILD


def test_normalize_blocked_defaults_to_planning():
    gate = normalize_pipeline_gate(ProjectState.AUTONOMOUSLY_BLOCKED, None)
    assert gate == ProjectState.PLANNING


def test_fail_from_planning_and_implementing():
    assert fail_project(ProjectState.PLANNING) == ProjectState.DIAGNOSING
    assert fail_project(ProjectState.IMPLEMENTING) == ProjectState.DIAGNOSING


def test_advance_implementing_to_unit_testing():
    assert advance_project(ProjectState.IMPLEMENTING) == ProjectState.UNIT_TESTING
