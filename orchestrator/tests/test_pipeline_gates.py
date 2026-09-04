from app.models import ProjectState
from app.state_machine import (
    PIPELINE_GATES,
    advance_project,
    fail_project,
    normalize_pipeline_gate,
    parse_project_state,
    pipeline_gate_index,
)


def test_pipeline_gate_order():
    assert PIPELINE_GATES[0] == ProjectState.PLANNING
    assert PIPELINE_GATES[-1] == ProjectState.REVIEW


def test_pipeline_gate_index():
    assert pipeline_gate_index(ProjectState.PLANNING) == 0
    assert pipeline_gate_index(ProjectState.IMPLEMENTING) == 1
    assert pipeline_gate_index(ProjectState.INTEGRATION_TESTING) == 2
    assert pipeline_gate_index(ProjectState.REVIEW) == 6
    assert pipeline_gate_index(ProjectState.DIAGNOSING) is None


def test_gates_named_for_their_stage():
    """Each gate runs its namesake stage — no off-by-one drift."""
    assert ProjectState.INTEGRATION_TESTING in PIPELINE_GATES
    assert ProjectState.DOCKER_BUILD in PIPELINE_GATES
    assert not hasattr(ProjectState, "UNIT_TESTING")


def test_normalize_diagnosing_uses_failed_gate():
    gate = normalize_pipeline_gate(ProjectState.DIAGNOSING, ProjectState.INTEGRATION_TESTING)
    assert gate == ProjectState.INTEGRATION_TESTING


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


def test_advance_implementing_goes_to_integration():
    assert advance_project(ProjectState.IMPLEMENTING) == ProjectState.INTEGRATION_TESTING


def test_parse_project_state_maps_legacy_unit_testing():
    assert parse_project_state("UNIT_TESTING") == ProjectState.INTEGRATION_TESTING
    assert parse_project_state("REVIEW") == ProjectState.REVIEW
