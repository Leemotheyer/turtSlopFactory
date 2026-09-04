from app.models import ProjectState
from app.state_machine import StateMachineError, advance_project, fail_project


def test_advance_happy_path():
    assert advance_project(ProjectState.REQUESTED) == ProjectState.DISCOVERY
    assert advance_project(ProjectState.DISCOVERY) == ProjectState.INTAKE_PENDING
    assert advance_project(ProjectState.INTAKE_PENDING) == ProjectState.PLANNING
    assert advance_project(ProjectState.PLANNING) == ProjectState.IMPLEMENTING


def test_fail_from_testing():
    assert fail_project(ProjectState.INTEGRATION_TESTING) == ProjectState.DIAGNOSING


def test_no_forward_from_production():
    try:
        advance_project(ProjectState.PRODUCTION)
        assert False, "expected StateMachineError"
    except StateMachineError:
        pass
