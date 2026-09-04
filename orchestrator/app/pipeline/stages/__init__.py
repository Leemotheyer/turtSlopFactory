"""Pipeline stage registry.

Each :class:`StageSpec` binds a pipeline gate (project state) to the executor
method that runs there. Gates are named for the stage that runs *at* that
state; substages run in order within a gate, driven by ``requires`` /
``completes`` context flags.

Stage bodies live in the sibling modules (``planning``, ``implementing``,
``testing``, ``enrichment``, ``build_deploy``, ``acceptance``, ``adversary``,
``review``, ``post_production``); the executor exposes thin ``_stage_*``
methods that delegate here so tests can monkeypatch individual stages.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import ProjectState

# Substage labels (project state stays at the gate while these run).
SUBSTAGE_IMPLEMENTING = "implementing"
SUBSTAGE_UNIT_TESTING = "unit_testing"
SUBSTAGE_ENRICHMENT = "enrichment"
SUBSTAGE_ADVERSARY = "adversary"
SUBSTAGE_ACCEPTANCE = "acceptance"
SUBSTAGE_USER_JOURNEY = "user_journey"
SUBSTAGE_REVIEW = "review"
SUBSTAGE_TESTING = "testing"


@dataclass(frozen=True)
class StageSpec:
    gate: ProjectState
    substage: str | None
    method: str
    # Context flag that must be truthy before this stage is due (substage ordering).
    requires: str | None = None
    # Context flag set when this stage has completed (skip when already set).
    completes: str | None = None


BUILD_STAGES: tuple[StageSpec, ...] = (
    StageSpec(ProjectState.PLANNING, None, "_stage_planning"),
    StageSpec(
        ProjectState.IMPLEMENTING,
        SUBSTAGE_IMPLEMENTING,
        "_stage_implementing",
        completes="implementation_complete",
    ),
    StageSpec(
        ProjectState.IMPLEMENTING,
        SUBSTAGE_UNIT_TESTING,
        "_stage_unit_testing",
        requires="implementation_complete",
        completes="unit_testing_complete",
    ),
    StageSpec(
        ProjectState.IMPLEMENTING,
        SUBSTAGE_ENRICHMENT,
        "_stage_autonomous_enrichment",
        requires="unit_testing_complete",
        completes="enrichment_complete",
    ),
    StageSpec(ProjectState.INTEGRATION_TESTING, None, "_stage_integration_testing"),
    StageSpec(ProjectState.DOCKER_BUILD, None, "_stage_docker_build"),
    StageSpec(ProjectState.STAGING_DEPLOY, None, "_stage_staging_deploy"),
    StageSpec(
        ProjectState.SMOKE_TESTING,
        None,
        "_stage_smoke_testing",
        completes="smoke_testing_complete",
    ),
    StageSpec(
        ProjectState.SMOKE_TESTING,
        SUBSTAGE_ENRICHMENT,
        "_stage_post_smoke_enrichment",
        requires="smoke_testing_complete",
        completes="post_smoke_enrichment_complete",
    ),
    StageSpec(
        ProjectState.SMOKE_TESTING,
        SUBSTAGE_ADVERSARY,
        "_stage_adversary",
        requires="post_smoke_enrichment_complete",
        completes="adversary_complete",
    ),
    StageSpec(
        ProjectState.SMOKE_TESTING,
        SUBSTAGE_ACCEPTANCE,
        "_stage_acceptance",
        requires="adversary_complete",
        completes="acceptance_complete",
    ),
    StageSpec(
        ProjectState.SMOKE_TESTING,
        SUBSTAGE_USER_JOURNEY,
        "_stage_user_journey",
        requires="acceptance_complete",
        completes="user_journey_complete",
    ),
    StageSpec(
        ProjectState.SMOKE_TESTING,
        SUBSTAGE_REVIEW,
        "_stage_review",
        requires="user_journey_complete",
    ),
)

POST_PRODUCTION_STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        ProjectState.PRODUCTION,
        SUBSTAGE_ENRICHMENT,
        "_stage_post_production_enrichment",
        completes="post_production_enrichment_complete",
    ),
    StageSpec(
        ProjectState.PRODUCTION,
        SUBSTAGE_TESTING,
        "_stage_post_production_testing",
        requires="post_production_enrichment_complete",
        completes="post_production_tests_complete",
    ),
    StageSpec(
        ProjectState.PRODUCTION,
        None,
        "_stage_post_production_redeploy",
        requires="post_production_tests_complete",
        completes="post_production_redeploy_complete",
    ),
)
