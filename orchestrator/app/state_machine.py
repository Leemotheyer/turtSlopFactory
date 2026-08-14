from app.models import (
    FAILURE_TRANSITIONS,
    FORWARD_TRANSITIONS,
    ProjectState,
)

# Ordered gates for the build pipeline (happy path only).
PIPELINE_GATES: tuple[ProjectState, ...] = (
    ProjectState.PLANNING,
    ProjectState.IMPLEMENTING,
    ProjectState.UNIT_TESTING,
    ProjectState.INTEGRATION_TESTING,
    ProjectState.DOCKER_BUILD,
    ProjectState.STAGING_DEPLOY,
    ProjectState.SMOKE_TESTING,
    ProjectState.REVIEW,
)

_PIPELINE_GATE_INDEX = {state: index for index, state in enumerate(PIPELINE_GATES)}


class StateMachineError(Exception):
    pass


def pipeline_gate_index(state: ProjectState) -> int | None:
    """Index of a pipeline gate, or None if not part of the build sequence."""
    return _PIPELINE_GATE_INDEX.get(state)


def normalize_pipeline_gate(
    state: ProjectState,
    failed_gate: ProjectState | None = None,
) -> ProjectState | None:
    """Map project state (including side states) to a pipeline gate for resume."""
    if state in _PIPELINE_GATE_INDEX:
        return state
    if state in (ProjectState.DIAGNOSING, ProjectState.FIXING):
        if failed_gate and failed_gate in _PIPELINE_GATE_INDEX:
            return failed_gate
        return ProjectState.IMPLEMENTING
    return None


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
