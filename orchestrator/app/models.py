from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ProjectState(StrEnum):
    REQUESTED = "REQUESTED"
    DISCOVERY = "DISCOVERY"
    INTAKE_PENDING = "INTAKE_PENDING"
    PLANNING = "PLANNING"
    IMPLEMENTING = "IMPLEMENTING"
    UNIT_TESTING = "UNIT_TESTING"
    INTEGRATION_TESTING = "INTEGRATION_TESTING"
    DOCKER_BUILD = "DOCKER_BUILD"
    STAGING_DEPLOY = "STAGING_DEPLOY"
    SMOKE_TESTING = "SMOKE_TESTING"
    REVIEW = "REVIEW"
    PRODUCTION = "PRODUCTION"
    DIAGNOSING = "DIAGNOSING"
    FIXING = "FIXING"
    AUTONOMOUSLY_BLOCKED = "AUTONOMOUSLY_BLOCKED"


class AgentRole(StrEnum):
    DISCOVERY = "discovery"
    ARCHITECT = "architect"
    DEVELOPER = "developer"
    TESTER = "tester"
    REVIEWER = "reviewer"


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ProjectCreate(BaseModel):
    name: str
    description: str
    repo_url: str | None = None
    branch: str = "main"
    base_branch: str | None = None
    isolate_branch: bool = True


class ProjectUpdate(BaseModel):
    repo_url: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    work_branch: str | None = None
    isolate_branch: bool | None = None
    clear_repo: bool = False


class Project(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str
    repo_url: str | None = None
    state: ProjectState = ProjectState.REQUESTED
    branch: str = "main"
    base_branch: str = "main"
    work_branch: str | None = None
    isolate_branch: bool = True
    merge_status: str | None = None
    image_tag: str | None = None
    preview_url: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TaskCreate(BaseModel):
    title: str
    description: str
    role: AgentRole = AgentRole.DEVELOPER


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    title: str
    description: str
    role: AgentRole
    status: TaskStatus = TaskStatus.QUEUED
    attempt: int = 1
    max_attempts: int = 5
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EventType(StrEnum):
    STATE_TRANSITION = "state.transition"
    AGENT_COMMAND_STARTED = "agent.command.started"
    AGENT_COMMAND_OUTPUT = "agent.command.output"
    AGENT_COMMAND_FINISHED = "agent.command.finished"
    TEST_COMPLETED = "test.completed"
    TASK_STATUS_CHANGED = "task.status.changed"
    DEPLOYMENT_STARTED = "deployment.started"
    DEPLOYMENT_FINISHED = "deployment.finished"
    PROGRESS_UPDATED = "progress.updated"
    NOTE_ADDED = "note.added"
    INPUT_REQUESTED = "input.requested"
    INPUT_RESOLVED = "input.resolved"
    DISCOVERY_STARTED = "discovery.started"
    DISCOVERY_COMPLETED = "discovery.completed"
    INTAKE_SUBMITTED = "intake.submitted"
    NOTIFICATION_CREATED = "notification.created"
    ENV_REQUIRED = "env.required"


class NotificationType(StrEnum):
    ENV_REQUIRED = "env_required"
    AGENT_QUESTION = "agent_question"
    PROJECT_FINISHED = "project_finished"
    INTAKE_READY = "intake_ready"
    REVIEW_READY = "review_ready"
    MERGE_READY = "merge_ready"
    PIPELINE_BLOCKED = "pipeline_blocked"
    PREVIEW_READY = "preview_ready"


class Notification(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID | None = None
    type: NotificationType
    title: str
    message: str
    action: str | None = None
    reference_id: UUID | None = None
    read: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SecretSet(BaseModel):
    key_name: str
    value: str
    description: str = ""


class SecretPublic(BaseModel):
    key_name: str
    masked_value: str
    description: str
    configured: bool


class EnvRequirementPublic(BaseModel):
    id: str
    key_name: str
    description: str
    requested_by: str
    status: str


class DiscoveryStatus(StrEnum):
    GENERATING = "generating"
    AWAITING_USER = "awaiting_user"
    SUBMITTED = "submitted"
    AUTO_SUBMITTED = "auto_submitted"


class IntakeFieldType(StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    SELECT = "select"
    MULTISELECT = "multiselect"


class IntakeField(BaseModel):
    id: str
    label: str
    type: IntakeFieldType = IntakeFieldType.TEXT
    help: str = ""
    placeholder: str = ""
    options: list[str] = Field(default_factory=list)
    required: bool = True
    default: str | None = None


class DiscoverySession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    status: DiscoveryStatus = DiscoveryStatus.GENERATING
    loose_plan: str = ""
    form_fields: list[IntakeField] = Field(default_factory=list)
    responses: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    submitted_at: datetime | None = None
    expires_at: datetime | None = None


class IntakeSubmit(BaseModel):
    responses: dict[str, str | list[str]]


class NoteType(StrEnum):
    INSTRUCTION = "instruction"
    FEATURE = "feature"
    SCOPE_OUT = "scope_out"
    GENERAL = "general"


class InputRequestStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    AUTO_RESOLVED = "auto_resolved"


class ProjectNoteCreate(BaseModel):
    content: str
    note_type: NoteType = NoteType.INSTRUCTION


class ProjectNote(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    content: str
    note_type: NoteType
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProgressEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    category: str
    title: str
    summary: str
    detail: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProgressDigest(BaseModel):
    project_id: UUID
    current_state: str
    pipeline_running: bool
    entries: list[ProgressEntry] = Field(default_factory=list)
    summary_lines: list[str] = Field(default_factory=list)


class InputRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    task_id: UUID | None = None
    agent_id: str
    role: str
    question: str
    context_detail: str = ""
    options: list[str] = Field(default_factory=list)
    default_decision: str
    status: InputRequestStatus = InputRequestStatus.OPEN
    human_response: str | None = None
    resolved_decision: str | None = None
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None


class InputRequestRespond(BaseModel):
    response: str


class FactoryEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: EventType
    project_id: UUID | None = None
    task_id: UUID | None = None
    agent_id: str | None = None
    payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Deployment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    environment: str
    image_tag: str
    url: str | None = None
    port: int | None = None
    container_id: str | None = None
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectDetail(Project):
    staging_url: str | None = None
    production_url: str | None = None
    preview_url: str | None = None
    preview_port: int | None = None
    preview_type: str | None = None
    preview_status: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    pipeline_running: bool = False
    discovery_status: str | None = None
    intake_ready: bool = False


# Valid forward transitions for the happy path
FORWARD_TRANSITIONS: dict[ProjectState, ProjectState] = {
    ProjectState.REQUESTED: ProjectState.DISCOVERY,
    ProjectState.DISCOVERY: ProjectState.INTAKE_PENDING,
    ProjectState.INTAKE_PENDING: ProjectState.PLANNING,
    ProjectState.PLANNING: ProjectState.IMPLEMENTING,
    ProjectState.IMPLEMENTING: ProjectState.UNIT_TESTING,
    ProjectState.UNIT_TESTING: ProjectState.INTEGRATION_TESTING,
    ProjectState.INTEGRATION_TESTING: ProjectState.DOCKER_BUILD,
    ProjectState.DOCKER_BUILD: ProjectState.STAGING_DEPLOY,
    ProjectState.STAGING_DEPLOY: ProjectState.SMOKE_TESTING,
    ProjectState.SMOKE_TESTING: ProjectState.REVIEW,
    ProjectState.REVIEW: ProjectState.PRODUCTION,
}

FAILURE_TRANSITIONS: dict[ProjectState, ProjectState] = {
    ProjectState.PLANNING: ProjectState.DIAGNOSING,
    ProjectState.IMPLEMENTING: ProjectState.DIAGNOSING,
    ProjectState.UNIT_TESTING: ProjectState.DIAGNOSING,
    ProjectState.INTEGRATION_TESTING: ProjectState.DIAGNOSING,
    ProjectState.DOCKER_BUILD: ProjectState.DIAGNOSING,
    ProjectState.STAGING_DEPLOY: ProjectState.DIAGNOSING,
    ProjectState.SMOKE_TESTING: ProjectState.DIAGNOSING,
    ProjectState.REVIEW: ProjectState.DIAGNOSING,
}
