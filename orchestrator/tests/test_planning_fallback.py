"""Planning stage fallback when cloud architect returns empty."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.base import AgentRun
from app.models import AgentRole


@pytest.mark.asyncio
async def test_planning_uses_requirements_draft_when_architect_fails(tmp_path):
    from app.pipeline.stages import planning as planning_mod
    from app.workspace.manager import WorkspaceManager

    project_id = uuid4()
    workspace = WorkspaceManager(str(tmp_path))
    draft = "# Requirements — Test\n\n## Product vision\nHello\n"

    project = MagicMock()
    project.id = project_id
    project.name = "Test"
    project.description = "A test app"

    context = {"requirements_draft": draft, "original_description": project.description}

    ex = MagicMock()
    ex.workspace = workspace
    ex.create_task = AsyncMock(return_value=MagicMock(id=uuid4()))
    ex.runner.run = AsyncMock(
        return_value=AgentRun(
            task_id=uuid4(),
            role=AgentRole.ARCHITECT,
            success=False,
            output="Cursor cloud architect finished without requirements.md / architecture.md in the reply.",
        )
    )
    ex.complete_task = AsyncMock()
    ex._persist_last_failure = MagicMock()
    ex._refresh_context = AsyncMock()
    ex._log_progress = AsyncMock()
    ex.transition = AsyncMock()

    async def fake_build_work_plan(ex_, session, proj, ctx):
        return [], {"units": []}, MagicMock(max_parallel=1)

    contract = MagicMock(version=1, requirements=[], source="fallback")

    session = AsyncMock()

    with patch.object(planning_mod, "build_work_plan", fake_build_work_plan):
        with patch.object(
            planning_mod,
            "draft_requirements_from_context",
            return_value=draft,
        ):
            with patch(
                "app.services.contracts.contract_from_planning",
                return_value=(contract, []),
            ):
                with patch(
                    "app.services.contracts.save_contract",
                    new_callable=AsyncMock,
                    return_value=contract,
                ):
                    with patch("app.services.contracts.write_contract_artifacts"):
                        with patch(
                            "app.services.contracts.sync_requirements_from_contract",
                            new_callable=AsyncMock,
                        ):
                            with patch("app.services.system_map.refresh_system_map"):
                                ok = await planning_mod.stage_planning(ex, session, project, context)

    assert ok is True
    assert "requirements.md" in workspace.list_artifacts(project_id)
    assert "architecture.md" in workspace.list_artifacts(project_id)
    ex._persist_last_failure.assert_not_called()
