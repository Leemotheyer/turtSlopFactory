from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.artifacts.schemas import ArchitectureDecisionDraft
from app.database import Base
from app.db_models import ProjectRow
from app.services.memory import (
    format_memory_for_prompt,
    load_project_memory,
    record_decisions,
    record_failure,
    record_known_issues,
    resolve_failures_for_gate,
    unresolved_regression_gaps,
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def project(db_session):
    row = ProjectRow(id=uuid4(), name="p", description="d")
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.mark.asyncio
async def test_decisions_deduplicate(db_session, project):
    drafts = [
        ArchitectureDecisionDraft(decision="Use PostgreSQL", reason="transactions"),
        ArchitectureDecisionDraft(decision="use postgresql", reason="dup casing"),
    ]
    added = await record_decisions(db_session, project.id, drafts)
    assert added == 1
    added_again = await record_decisions(db_session, project.id, drafts)
    assert added_again == 0


@pytest.mark.asyncio
async def test_failure_lifecycle_and_regression_gap(db_session, project, tmp_path):
    failure_id = await record_failure(
        db_session,
        project.id,
        gate="IMPLEMENTING",
        substage="unit_testing",
        error_class="app",
        summary="assert 500 == 200",
        attempt=1,
    )
    assert failure_id is not None

    resolved = await resolve_failures_for_gate(
        db_session, project.id, "IMPLEMENTING", resolution="fixed"
    )
    assert resolved == 1

    # No regression test on disk yet → gap reported.
    gaps = await unresolved_regression_gaps(db_session, project.id, repo=tmp_path)
    assert len(gaps) == 1
    expected = gaps[0]["expected_test"]
    assert expected.startswith("test_fix_")

    # Writing the expected regression test closes the gap.
    regression_dir = tmp_path / "tests" / "regression"
    regression_dir.mkdir(parents=True)
    (regression_dir / expected).write_text("def test_ok():\n    assert True\n")
    gaps = await unresolved_regression_gaps(db_session, project.id, repo=tmp_path)
    assert gaps == []


@pytest.mark.asyncio
async def test_infra_failures_never_require_regression_tests(db_session, project, tmp_path):
    await record_failure(
        db_session, project.id,
        gate="DOCKER_BUILD", substage=None,
        error_class="infra", summary="docker daemon down", attempt=1,
    )
    await resolve_failures_for_gate(db_session, project.id, "DOCKER_BUILD", resolution="retried")
    gaps = await unresolved_regression_gaps(db_session, project.id, repo=tmp_path)
    assert gaps == []


@pytest.mark.asyncio
async def test_memory_prompt_section_is_bounded(db_session, project):
    await record_decisions(
        db_session, project.id,
        [ArchitectureDecisionDraft(decision="D" * 500, reason="R" * 500) for _ in range(5)],
    )
    await record_known_issues(
        db_session, project.id,
        [{"description": "issue " + "x" * 400, "severity": "high"} for _ in range(5)],
    )
    memory = await load_project_memory(db_session, project.id)
    text = format_memory_for_prompt(memory)
    assert "Project memory" in text
    assert len(text) <= 1800


@pytest.mark.asyncio
async def test_known_issues_deduplicate(db_session, project):
    issues = [{"description": "5xx on empty payload", "severity": "high", "source": "adversary"}]
    assert await record_known_issues(db_session, project.id, issues) == 1
    assert await record_known_issues(db_session, project.id, issues) == 0
