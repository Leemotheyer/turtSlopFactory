from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from app.models import AgentRole


@dataclass
class AgentRun:
    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None
    role: AgentRole = AgentRole.DEVELOPER
    agent_id: str = ""
    cursor_url: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    success: bool = False
    output: str = ""


@dataclass
class AgentEvent:
    type: str
    agent_id: str
    task_id: UUID | None = None
    payload: dict = field(default_factory=dict)


class AgentRunner(ABC):
    @abstractmethod
    async def run(
        self,
        role: AgentRole,
        project_id: UUID,
        task_id: UUID,
        workspace: str,
        context: dict,
    ) -> AgentRun:
        ...

    @abstractmethod
    async def stream_events(self, run_id: UUID) -> AsyncIterator[AgentEvent]:
        ...
