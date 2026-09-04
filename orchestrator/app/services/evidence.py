"""Requirement → evidence graph: recording and acceptance evaluation."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import ProjectContract
from app.db_models import EvidenceRow, RequirementRow

logger = logging.getLogger(__name__)

# test_r1_health / test_R2_crud → requirement key
_TEST_REQ_RE = re.compile(r"^test_([a-zA-Z][a-zA-Z0-9]{0,15}?)_", re.IGNORECASE)


async def sync_requirements_from_contract(
    session: AsyncSession, project_id: UUID, contract: ProjectContract
) -> None:
    """Upsert requirement rows for the contract; drop rows no longer present."""
    result = await session.execute(
        select(RequirementRow).where(RequirementRow.project_id == project_id)
    )
    existing = {row.req_id: row for row in result.scalars()}
    contract_ids = set()

    for req in contract.requirements:
        contract_ids.add(req.id)
        row = existing.get(req.id)
        if row is None:
            session.add(
                RequirementRow(
                    project_id=project_id,
                    req_id=req.id,
                    description=req.description,
                    acceptance=req.acceptance,
                    contract_version=contract.version,
                )
            )
        else:
            row.description = req.description
            row.acceptance = req.acceptance
            row.contract_version = contract.version
            if row.status == "waived":
                pass  # human waivers survive contract refreshes
            row.updated_at = datetime.utcnow()

    for req_id, row in existing.items():
        if req_id not in contract_ids:
            await session.delete(row)

    await session.commit()


async def _requirement_by_key(
    session: AsyncSession, project_id: UUID, key: str | None
) -> RequirementRow | None:
    if not key:
        return None
    result = await session.execute(
        select(RequirementRow).where(
            RequirementRow.project_id == project_id,
            RequirementRow.req_id == str(key).strip().upper(),
        )
    )
    return result.scalar_one_or_none()


async def find_requirement_by_keyword(
    session: AsyncSession, project_id: UUID, *keywords: str
) -> RequirementRow | None:
    result = await session.execute(
        select(RequirementRow).where(RequirementRow.project_id == project_id)
    )
    for row in result.scalars():
        text = (row.description + " " + " ".join(row.acceptance or [])).lower()
        if any(k.lower() in text for k in keywords):
            return row
    return None


async def record_evidence(
    session: AsyncSession,
    project_id: UUID,
    *,
    kind: str,
    reference: str,
    passed: bool,
    payload: dict | None = None,
    requirement_key: str | None = None,
) -> None:
    requirement = await _requirement_by_key(session, project_id, requirement_key)
    session.add(
        EvidenceRow(
            project_id=project_id,
            requirement_id=requirement.id if requirement else None,
            kind=kind,
            reference=reference[:512],
            passed=passed,
            payload=payload or {},
        )
    )
    await session.commit()


async def record_probe_evidence(
    session: AsyncSession,
    project_id: UUID,
    *,
    probe: str,
    passed: bool,
    detail: str = "",
    health_path: str = "/health",
) -> None:
    """Record a live-preview probe; health probes link to the health requirement."""
    requirement = None
    if "health" in probe:
        requirement = await find_requirement_by_keyword(session, project_id, "health")
    session.add(
        EvidenceRow(
            project_id=project_id,
            requirement_id=requirement.id if requirement else None,
            kind="probe",
            reference=probe,
            passed=passed,
            payload={"detail": detail[:1000], "health_path": health_path},
        )
    )
    await session.commit()


def parse_junit_results(xml_text: str) -> list[dict]:
    """Flatten a junit XML report into [{name, classname, passed}]."""
    results: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return results
    for case in root.iter("testcase"):
        failed = any(child.tag in ("failure", "error") for child in case)
        skipped = any(child.tag == "skipped" for child in case)
        if skipped:
            continue
        results.append(
            {
                "name": case.get("name", ""),
                "classname": case.get("classname", ""),
                "passed": not failed,
            }
        )
    return results


def requirement_key_for_test(test_name: str) -> str | None:
    match = _TEST_REQ_RE.match(test_name or "")
    if not match:
        return None
    key = match.group(1).upper()
    # Only treat R-style ids (R1, R12, AUTH1…) as requirement references when
    # they look like short identifiers, not ordinary words (test_create_item).
    if re.fullmatch(r"[A-Z]{1,4}\d{1,3}", key):
        return key
    return None


async def record_test_results_evidence(
    session: AsyncSession,
    workspace,
    project_id: UUID,
    *,
    stage: str,
) -> None:
    """Parse the junit XML for a test stage into per-requirement evidence rows."""
    xml_path = workspace.logs_dir(project_id) / f"pytest-{stage}.xml"
    if not xml_path.is_file():
        return
    try:
        results = parse_junit_results(xml_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        logger.warning("Could not parse junit results for %s/%s", project_id, stage)
        return
    if not results:
        return

    overall_passed = all(r["passed"] for r in results)
    session.add(
        EvidenceRow(
            project_id=project_id,
            kind="test_run",
            reference=f"pytest:{stage}",
            passed=overall_passed,
            payload={"total": len(results), "failed": sum(1 for r in results if not r["passed"])},
        )
    )

    # Per-requirement rollup: a requirement fails when any of its mapped tests fail.
    per_req: dict[str, list[dict]] = {}
    for result in results:
        key = requirement_key_for_test(result["name"])
        if key:
            per_req.setdefault(key, []).append(result)

    for key, tests in per_req.items():
        requirement = await _requirement_by_key(session, project_id, key)
        if requirement is None:
            continue
        passed = all(t["passed"] for t in tests)
        session.add(
            EvidenceRow(
                project_id=project_id,
                requirement_id=requirement.id,
                kind="test_run",
                reference=f"pytest:{stage}:{key}",
                passed=passed,
                payload={"tests": [t["name"] for t in tests][:20], "stage": stage},
            )
        )
    await session.commit()


async def evaluate_acceptance(
    session: AsyncSession, project_id: UUID, contract: ProjectContract
) -> dict:
    """Deterministic acceptance evaluation: latest evidence decides each requirement.

    Statuses: ``verified`` (has evidence, latest per source passes), ``failed``
    (latest evidence failing), ``unverified`` (no evidence), ``waived`` (human).
    """
    result = await session.execute(
        select(RequirementRow).where(RequirementRow.project_id == project_id)
    )
    requirements = {row.req_id: row for row in result.scalars()}

    evidence_result = await session.execute(
        select(EvidenceRow)
        .where(EvidenceRow.project_id == project_id)
        .order_by(EvidenceRow.created_at.asc())
    )
    evidence_by_req: dict[UUID, list[EvidenceRow]] = {}
    for row in evidence_result.scalars():
        if row.requirement_id is not None:
            evidence_by_req.setdefault(row.requirement_id, []).append(row)

    report: dict = {"requirements": {}, "total": 0, "verified": 0, "all_verified": False}
    verified_count = 0
    blocking_reqs = [r for r in contract.requirements if r.priority == "must"] or list(
        contract.requirements
    )
    blocking_ids = {r.id for r in blocking_reqs}

    for req in contract.requirements:
        row = requirements.get(req.id)
        entry: dict = {
            "description": req.description,
            "acceptance": req.acceptance,
            "priority": req.priority,
            "status": "unverified",
            "evidence": [],
            "evidence_summary": "",
        }
        if row is None:
            report["requirements"][req.id] = entry
            if req.id in blocking_ids:
                report["total"] += 1
            continue

        if row.status == "waived":
            entry["status"] = "waived"
            if req.id in blocking_ids:
                verified_count += 1
                report["total"] += 1
            report["requirements"][req.id] = entry
            continue

        rows = evidence_by_req.get(row.id, [])
        if not rows:
            entry["status"] = "unverified"
        else:
            # Latest evidence per (kind, reference) source decides; any failing
            # latest source fails the requirement.
            latest: dict[tuple[str, str], EvidenceRow] = {}
            for ev in rows:
                latest[(ev.kind, ev.reference)] = ev
            passing = [ev for ev in latest.values() if ev.passed]
            failing = [ev for ev in latest.values() if not ev.passed]
            if failing:
                entry["status"] = "failed"
            elif passing:
                entry["status"] = "verified"
            entry["evidence"] = [
                {
                    "kind": ev.kind,
                    "reference": ev.reference,
                    "passed": ev.passed,
                    "at": ev.created_at.isoformat(),
                }
                for ev in list(latest.values())[-10:]
            ]
            entry["evidence_summary"] = ", ".join(
                f"{ev.kind}:{ev.reference}={'pass' if ev.passed else 'FAIL'}"
                for ev in list(latest.values())[:6]
            )

        new_status = entry["status"]
        if row.status != "waived" and row.status != new_status:
            row.status = new_status
            row.updated_at = datetime.utcnow()

        if new_status in ("verified", "waived"):
            if req.id in blocking_ids:
                verified_count += 1
        report["requirements"][req.id] = entry
        if req.id in blocking_ids:
            report["total"] += 1

    await session.commit()
    report["verified"] = verified_count
    report["blocking_total"] = len(blocking_ids)
    report["all_verified"] = report["total"] > 0 and verified_count == report["total"]
    if report["total"] == 0:
        report["all_verified"] = True
    return report


async def list_requirements_with_evidence(
    session: AsyncSession, project_id: UUID
) -> list[dict]:
    """Dashboard payload: every requirement with its evidence trail."""
    result = await session.execute(
        select(RequirementRow)
        .where(RequirementRow.project_id == project_id)
        .order_by(RequirementRow.req_id.asc())
    )
    requirement_rows = list(result.scalars())
    evidence_result = await session.execute(
        select(EvidenceRow)
        .where(EvidenceRow.project_id == project_id)
        .order_by(EvidenceRow.created_at.desc())
    )
    evidence_by_req: dict[UUID, list[EvidenceRow]] = {}
    unlinked: list[EvidenceRow] = []
    for row in evidence_result.scalars():
        if row.requirement_id is not None:
            evidence_by_req.setdefault(row.requirement_id, []).append(row)
        else:
            unlinked.append(row)

    payload = []
    for req in requirement_rows:
        payload.append(
            {
                "req_id": req.req_id,
                "description": req.description,
                "acceptance": req.acceptance or [],
                "status": req.status,
                "contract_version": req.contract_version,
                "evidence": [
                    {
                        "kind": ev.kind,
                        "reference": ev.reference,
                        "passed": ev.passed,
                        "payload": ev.payload,
                        "created_at": ev.created_at.isoformat(),
                    }
                    for ev in evidence_by_req.get(req.id, [])[:25]
                ],
            }
        )
    return payload


async def project_health(session: AsyncSession, project_id: UUID) -> dict:
    """Evidence-backed health: % of requirements verified, with counts."""
    result = await session.execute(
        select(RequirementRow.status).where(RequirementRow.project_id == project_id)
    )
    statuses = [row[0] for row in result]
    total = len(statuses)
    verified = sum(1 for s in statuses if s in ("verified", "waived"))
    failed = sum(1 for s in statuses if s == "failed")
    return {
        "total_requirements": total,
        "verified": verified,
        "failed": failed,
        "unverified": total - verified - failed,
        "health_percent": round(100 * verified / total) if total else None,
    }


async def set_requirement_status(
    session: AsyncSession, project_id: UUID, req_id: str, status: str
) -> bool:
    row = await _requirement_by_key(session, project_id, req_id)
    if row is None:
        return False
    row.status = status
    row.updated_at = datetime.utcnow()
    await session.commit()
    return True
