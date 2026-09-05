"""Pydantic schemas for every JSON artifact agents produce.

These replace ad-hoc regex extraction + ``json.loads`` scattered through the
runners. Use :func:`app.artifacts.parsing.parse_agent_json` to parse free-form
agent replies against one of these models.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Artifact(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EnrichmentFeature(_Artifact):
    id: str = ""
    title: str = ""
    description: str = ""
    scope: str = "in_scope"  # in_scope | uncertain | out_of_scope
    priority: str = "medium"
    tier: str = "polish"  # milestone | polish

    @field_validator("tier", mode="before")
    @classmethod
    def _normalize_tier(cls, value):
        value = str(value or "polish").lower()
        return value if value in ("milestone", "polish") else "polish"


class EnrichmentPlan(_Artifact):
    features: list[EnrichmentFeature] = Field(default_factory=list)
    quality_issues: list[str] = Field(default_factory=list)
    stop_reason: str | None = None

    @field_validator("quality_issues", mode="before")
    @classmethod
    def _coerce_issues(cls, value):
        if value is None:
            return []
        return [str(v) for v in value]


class ReviewReport(_Artifact):
    decision: str = "reject"  # approve | reject
    checklist: dict[str, bool] = Field(default_factory=dict)
    concerns: list[str] = Field(default_factory=list)
    severity: str = "low"

    @property
    def approved(self) -> bool:
        return self.decision == "approve"


class AdversaryFinding(_Artifact):
    severity: str = "medium"  # low | medium | high
    requirement_id: str | None = None
    description: str = ""
    reproduction: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, value):
        value = str(value or "medium").lower()
        return value if value in ("low", "medium", "high") else "medium"


class AdversaryReport(_Artifact):
    findings: list[AdversaryFinding] = Field(default_factory=list)
    notes: str = ""


class UserJourneyStep(_Artifact):
    action: str = ""
    target: str = ""
    success: bool = False
    detail: str = ""


class UserJourneyFinding(_Artifact):
    severity: str = "medium"  # low | medium | high
    category: str = "ux_improvement"  # blocking | ux_improvement
    title: str = ""
    description: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, value):
        value = str(value or "medium").lower()
        return value if value in ("low", "medium", "high") else "medium"


class UserJourneyReport(_Artifact):
    passed: bool = False
    steps: list[UserJourneyStep] = Field(default_factory=list)
    blocking_findings: list[UserJourneyFinding] = Field(default_factory=list)
    ux_improvements: list[UserJourneyFinding] = Field(default_factory=list)
    intake_expectations: list[str] = Field(default_factory=list)
    notes: str = ""


class ContractRequirementDraft(_Artifact):
    id: str = ""
    description: str = ""
    acceptance: list[str] = Field(default_factory=list)
    priority: str = "must"


class ArchitectureDecisionDraft(_Artifact):
    decision: str = ""
    reason: str = ""
    alternatives: list[str] = Field(default_factory=list)
    tradeoffs: str = ""


class ContractDraft(_Artifact):
    """Architect planning output: contract + optional decision log."""

    goal: str = ""
    users: list[str] = Field(default_factory=list)
    requirements: list[ContractRequirementDraft] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    quality_targets: list[str] = Field(default_factory=list)
    security_requirements: list[str] = Field(default_factory=list)
    decisions: list[ArchitectureDecisionDraft] = Field(default_factory=list)


class RepoExplorationReport(_Artifact):
    classification: str = ""
    summary: str = ""
    stack: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
