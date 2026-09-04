from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.contract import ContractRequirement, ProjectContract
from app.database import Base
from app.db_models import ProjectRow
from app.services.evidence import (
    evaluate_acceptance,
    parse_junit_results,
    project_health,
    record_evidence,
    record_test_results_evidence,
    requirement_key_for_test,
    set_requirement_status,
    sync_requirements_from_contract,
)

_JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="3">
    <testcase classname="tests.test_app" name="test_r1_health" time="0.01"/>
    <testcase classname="tests.test_app" name="test_r2_create_and_list_items" time="0.01">
      <failure message="assert 500 == 201">boom</failure>
    </testcase>
    <testcase classname="tests.test_app" name="test_info" time="0.01"/>
  </testsuite>
</testsuites>
"""


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


def _contract() -> ProjectContract:
    return ProjectContract(
        goal="demo",
        requirements=[
            ContractRequirement(id="R1", description="health endpoint", acceptance=["200 ok"]),
            ContractRequirement(id="R2", description="items api", acceptance=["crud works"]),
        ],
        version=1,
    )


def test_requirement_key_extraction():
    assert requirement_key_for_test("test_r1_health") == "R1"
    assert requirement_key_for_test("test_R12_bulk_export") == "R12"
    assert requirement_key_for_test("test_auth1_login") == "AUTH1"
    assert requirement_key_for_test("test_create_item") is None
    assert requirement_key_for_test("test_info") is None


def test_parse_junit_results():
    results = parse_junit_results(_JUNIT)
    assert len(results) == 3
    by_name = {r["name"]: r["passed"] for r in results}
    assert by_name["test_r1_health"] is True
    assert by_name["test_r2_create_and_list_items"] is False


@pytest.mark.asyncio
async def test_junit_evidence_maps_to_requirements(db_session, workspace):
    project_id = uuid4()
    db_session.add(ProjectRow(id=project_id, name="p", description="d"))
    await db_session.commit()

    contract = _contract()
    await sync_requirements_from_contract(db_session, project_id, contract)

    xml_path = workspace.logs_dir(project_id) / "pytest-unit.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(_JUNIT)

    await record_test_results_evidence(db_session, workspace, project_id, stage="unit")

    report = await evaluate_acceptance(db_session, project_id, contract)
    assert report["requirements"]["R1"]["status"] == "verified"
    assert report["requirements"]["R2"]["status"] == "failed"
    assert report["all_verified"] is False

    health = await project_health(db_session, project_id)
    assert health["total_requirements"] == 2
    assert health["verified"] == 1
    assert health["failed"] == 1


@pytest.mark.asyncio
async def test_latest_evidence_wins_after_fix(db_session, workspace):
    project_id = uuid4()
    db_session.add(ProjectRow(id=project_id, name="p", description="d"))
    await db_session.commit()
    contract = _contract()
    await sync_requirements_from_contract(db_session, project_id, contract)

    await record_evidence(
        db_session, project_id, kind="test_run", reference="pytest:unit:R2",
        passed=False, requirement_key="R2",
    )
    await record_evidence(
        db_session, project_id, kind="test_run", reference="pytest:unit:R2",
        passed=True, requirement_key="R2",
    )
    await record_evidence(
        db_session, project_id, kind="test_run", reference="pytest:unit:R1",
        passed=True, requirement_key="R1",
    )

    report = await evaluate_acceptance(db_session, project_id, contract)
    assert report["requirements"]["R2"]["status"] == "verified"
    assert report["all_verified"] is True


@pytest.mark.asyncio
async def test_unverified_without_evidence_and_waiver(db_session):
    project_id = uuid4()
    db_session.add(ProjectRow(id=project_id, name="p", description="d"))
    await db_session.commit()
    contract = _contract()
    await sync_requirements_from_contract(db_session, project_id, contract)

    report = await evaluate_acceptance(db_session, project_id, contract)
    assert report["requirements"]["R1"]["status"] == "unverified"
    assert report["all_verified"] is False

    # Human waiver counts as verified for gating purposes.
    assert await set_requirement_status(db_session, project_id, "r1", "waived")
    assert await set_requirement_status(db_session, project_id, "r2", "waived")
    report = await evaluate_acceptance(db_session, project_id, contract)
    assert report["all_verified"] is True


@pytest.mark.asyncio
async def test_contract_resync_drops_removed_requirements(db_session):
    project_id = uuid4()
    db_session.add(ProjectRow(id=project_id, name="p", description="d"))
    await db_session.commit()
    await sync_requirements_from_contract(db_session, project_id, _contract())

    smaller = ProjectContract(
        goal="demo",
        requirements=[ContractRequirement(id="R1", description="health", acceptance=["ok"])],
        version=2,
    )
    await sync_requirements_from_contract(db_session, project_id, smaller)
    health = await project_health(db_session, project_id)
    assert health["total_requirements"] == 1
