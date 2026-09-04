import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    repo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    state: Mapped[str] = mapped_column(String(64), nullable=False, default="REQUESTED")
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    base_branch: Mapped[str] = mapped_column(String(64), nullable=False, default="main")
    work_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    isolate_branch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    merge_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    image_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_enrichment_passes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_budget_files: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_budget_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_fix_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adversary_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enforce_change_budget: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks: Mapped[list["TaskRow"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    notes: Mapped[list["ProjectNoteRow"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    progress_entries: Mapped[list["ProgressEntryRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    input_requests: Mapped[list["InputRequestRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    discovery: Mapped["DiscoverySessionRow | None"] = relationship(
        back_populates="project", cascade="all, delete-orphan", uselist=False
    )
    secrets: Mapped[list["ProjectSecretRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    env_requirements: Mapped[list["EnvRequirementRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["NotificationRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectSecretRow(Base):
    __tablename__ = "project_secrets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    key_name: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project: Mapped[ProjectRow] = relationship(back_populates="secrets")


class EnvRequirementRow(Base):
    __tablename__ = "env_requirements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    key_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False, default="agent")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[ProjectRow] = relationship(back_populates="env_requirements")


class NotificationRow(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[ProjectRow | None] = relationship(back_populates="notifications")


class FactorySettingsRow(Base):
    __tablename__ = "factory_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    agent_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="cursor_cloud")
    agent_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_models: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    max_parallel_agents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cursor_concurrent_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_github_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    setup_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    global_agent_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CursorConnectionRow(Base):
    __tablename__ = "cursor_connection"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enterprise_billing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DiscoverySessionRow(Base):
    __tablename__ = "discovery_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="generating")
    loose_plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    form_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    responses: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[ProjectRow] = relationship(back_populates="discovery")


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="developer")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="QUEUED")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project: Mapped[ProjectRow] = relationship(back_populates="tasks")


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeploymentRow(Base):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    image_tag: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    previous_tag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectNoteRow(Base):
    __tablename__ = "project_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[str] = mapped_column(String(64), nullable=False, default="instruction")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[ProjectRow] = relationship(back_populates="notes")


class ProgressEntryRow(Base):
    __tablename__ = "progress_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[ProjectRow] = relationship(back_populates="progress_entries")


class InputRequestRow(Base):
    __tablename__ = "input_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    default_decision: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="open")
    human_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[ProjectRow] = relationship(back_populates="input_requests")


class ProjectContractRow(Base):
    """Versioned project contract: requirements with acceptance criteria."""

    __tablename__ = "project_contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="architect")
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RequirementRow(Base):
    """A contract requirement tracked through the evidence graph."""

    __tablename__ = "requirements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    req_id: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    acceptance: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class EvidenceRow(Base):
    """A single piece of evidence linking work to a requirement (or the project)."""

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # test_run | probe | build | review | adversary | change_stats
    reference: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ArchitectureDecisionRow(Base):
    """Why-did-we-do-this memory: significant decisions with reasoning."""

    __tablename__ = "architecture_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    alternatives: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tradeoffs: Mapped[str] = mapped_column(Text, nullable=False, default="")
    agent_role: Mapped[str] = mapped_column(String(32), nullable=False, default="architect")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FailureRecordRow(Base):
    """Failure memory: what went wrong, how often, and how it was resolved."""

    __tablename__ = "failure_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    gate: Mapped[str] = mapped_column(String(64), nullable=False)
    substage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_class: Mapped[str] = mapped_column(String(32), nullable=False, default="app")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    regression_test: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KnownIssueRow(Base):
    """Open bugs / tech debt discovered by testers, adversary, or humans."""

    __tablename__ = "known_issues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="tester")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PipelineRunRow(Base):
    """Outcome metrics for one pipeline run (iterations, interventions, result)."""

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="build")
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fix_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    infra_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_interventions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_resolved_inputs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gates_failed: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    prompt_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
