from app.models import (
    FAILURE_TRANSITIONS,
    FORWARD_TRANSITIONS,
    ProjectState,
)


class StateMachineError(Exception):
    pass


def advance_project(project_state: ProjectState) -> ProjectState:
    """Move project to the next gate on the happy path."""
    next_state = FORWARD_TRANSITIONS.get(project_state)
    if next_state is None:
        raise StateMachineError(f"No forward transition from {project_state}")
    return next_state


def fail_project(project_state: ProjectState) -> ProjectState:
    """Move project into diagnosing after a gate failure."""
    next_state = FAILURE_TRANSITIONS.get(project_state)
    if next_state is None:
        raise StateMachineError(f"No failure transition from {project_state}")
    return next_state


def begin_fix() -> ProjectState:
    return ProjectState.FIXING


def finish_fix(return_to: ProjectState) -> ProjectState:
    """After fixing, re-enter the gate that failed."""
    return return_to


def block_autonomous() -> ProjectState:
    return ProjectState.AUTONOMOUSLY_BLOCKED
