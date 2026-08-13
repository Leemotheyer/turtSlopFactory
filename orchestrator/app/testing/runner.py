"""Test execution helpers."""

from app.agents.local_runner import LocalAgentRunner
from app.workspace.manager import WorkspaceManager


class TestRunner:
    def __init__(self) -> None:
        self.agent = LocalAgentRunner(WorkspaceManager())

    async def run_unit(self, project_id, context: dict):
        return await self.agent._tester(project_id, {**context, "test_stage": "unit"})

    async def run_integration(self, project_id, context: dict):
        return await self.agent._tester(project_id, {**context, "test_stage": "integration"})

    async def run_smoke(self, project_id, context: dict):
        return await self.agent._tester(project_id, {**context, "test_stage": "smoke"})
