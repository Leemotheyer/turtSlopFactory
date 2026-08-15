from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.feedback_pipeline import (
    should_schedule_feedback_on_input_response,
    wants_merge_to_main,
)


def test_wants_merge_to_main():
    assert wants_merge_to_main("Merge to main now", "Merge factory branch?")
    assert not wants_merge_to_main("Keep on factory branch", "Merge factory branch?")


def test_should_not_restart_on_reviewer_rate_limit_skip():
    assert not should_schedule_feedback_on_input_response(
        "skip",
        "Should rate limiting be required before approving this build?",
        role="reviewer",
    )
    assert not should_schedule_feedback_on_input_response(
        "Defer to v2",
        "Should rate limiting be required before approving this build?",
        role="reviewer",
    )


def test_should_not_restart_on_merge_branch_prompt():
    assert not should_schedule_feedback_on_input_response(
        "Keep on factory branch for now",
        "Merge factory branch `cursor/foo` into `main` now?",
    )


def test_should_restart_on_enrichment_scope_approval():
    assert should_schedule_feedback_on_input_response(
        "Yes, implement it",
        'The factory wants to add "OAuth". This may be out of scope — implement it?',
        role="architect",
    )
    assert not should_schedule_feedback_on_input_response(
        "Skip for now — not in v1 scope",
        'The factory wants to add "OAuth". This may be out of scope — implement it?',
        role="architect",
    )


@pytest.mark.asyncio
async def test_maybe_schedule_feedback_pipeline_only_at_review():
    from app.services.feedback_pipeline import maybe_schedule_feedback_pipeline

    project_id = uuid4()
    session = AsyncMock()
    row = MagicMock()
    row.state = "IMPLEMENTING"
    session.get.return_value = row

    with patch("app.services.feedback_pipeline.pipeline_executor") as executor:
        executor.is_running.return_value = False
        assert await maybe_schedule_feedback_pipeline(session, project_id) is False


@pytest.mark.asyncio
async def test_maybe_schedule_feedback_pipeline_at_review():
    from app.services.feedback_pipeline import maybe_schedule_feedback_pipeline

    project_id = uuid4()
    session = AsyncMock()
    row = MagicMock()
    row.state = "REVIEW"
    session.get.return_value = row

    with patch("app.services.feedback_pipeline.pipeline_executor") as executor, patch(
        "app.services.feedback_pipeline.schedule_pipeline", return_value=True
    ) as schedule:
        executor.is_running.return_value = False
        assert await maybe_schedule_feedback_pipeline(session, project_id) is True
        schedule.assert_called_once_with(project_id)
