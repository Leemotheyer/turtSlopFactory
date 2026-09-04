"""Contract lifecycle: generation, persistence, coverage, repo mirroring."""

from __future__ import annotations

import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.parsing import parse_agent_json
from app.artifacts.schemas import ArchitectureDecisionDraft, ContractDraft
from app.contract import ContractRequirement, ProjectContract, RuntimeSpec
from app.db_models import ProjectContractRow, ProjectRow
from app.services.work_planner import WorkUnit

logger = logging.getLogger(__name__)

CONTRACT_ARTIFACT = "contract.json"
CONTRACT_REPO_FILE = "project.contract.yaml"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def get_latest_contract(session: AsyncSession, project_id: UUID) -> ProjectContract | None:
    result = await session.execute(
        select(ProjectContractRow)
        .where(ProjectContractRow.project_id == project_id)
        .order_by(ProjectContractRow.version.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    try:
        contract = ProjectContract.model_validate(row.data)
    except Exception:
        logger.warning("Stored contract v%s for %s is invalid", row.version, project_id)
        return None
    contract.version = row.version
    contract.source = row.source
    return contract


async def save_contract(
    session: AsyncSession,
    project_id: UUID,
    contract: ProjectContract,
    *,
    source: str = "architect",
) -> ProjectContract:
    """Persist a new contract version (no-op when identical to the latest)."""
    latest = await session.execute(
        select(ProjectContractRow)
        .where(ProjectContractRow.project_id == project_id)
        .order_by(ProjectContractRow.version.desc())
        .limit(1)
    )
    latest_row = latest.scalar_one_or_none()

    payload = contract.model_dump(exclude={"version", "source"})
    if latest_row is not None:
        stored = dict(latest_row.data)
        stored.pop("version", None)
        stored.pop("source", None)
        if stored == payload:
            contract.version = latest_row.version
            contract.source = latest_row.source
            return contract

    version = (latest_row.version + 1) if latest_row is not None else 1
    row = ProjectContractRow(
        project_id=project_id,
        version=version,
        source=source,
        data=payload,
    )
    session.add(row)
    await session.commit()
    contract.version = version
    contract.source = source
    return contract


async def contract_history(session: AsyncSession, project_id: UUID) -> list[dict]:
    result = await session.execute(
        select(ProjectContractRow)
        .where(ProjectContractRow.project_id == project_id)
        .order_by(ProjectContractRow.version.desc())
    )
    return [
        {
            "version": row.version,
            "source": row.source,
            "created_at": row.created_at.isoformat(),
        }
        for row in result.scalars()
    ]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def fallback_contract(project: ProjectRow, context: dict) -> ProjectContract:
    """Deterministic contract when no architect draft is parseable.

    Only includes requirements the factory can verify without an LLM, so the
    deterministic local pipeline stays green end-to-end.
    """
    description = (context.get("original_description") or project.description or "").strip()
    analysis = context.get("repo_analysis") or {}
    existing = bool(analysis.get("has_existing_app"))

    requirements = [
        ContractRequirement(
            id="R1",
            description="Service exposes a working health endpoint",
            acceptance=[
                "GET /health returns HTTP 200",
                "Response body reports an ok/healthy status",
            ],
        )
    ]
    if not existing:
        requirements.append(
            ContractRequirement(
                id="R2",
                description="REST API supports creating, listing, and fetching items",
                acceptance=[
                    "POST /api/items creates an item and returns 201",
                    "GET /api/items lists created items",
                    "GET /api/items/{id} returns 404 for unknown ids",
                ],
            )
        )
        requirements.append(
            ContractRequirement(
                id="R3",
                description="Web UI is served and usable in a browser",
                acceptance=[
                    "GET / returns an HTML page",
                    "The page is wired to the API with relative URLs",
                ],
            )
        )

    non_goals = [
        note.get("content", "")
        for note in context.get("notes") or []
        if note.get("type") == "scope_out" and note.get("content")
    ]
    quality_targets = ["All pytest suites pass", "App works through the factory live preview"]
    intake = context.get("intake") or {}
    success = intake.get("success_criteria")
    if success:
        quality_targets.append(str(success))

    return ProjectContract(
        goal=description[:2000] or project.name,
        requirements=requirements,
        non_goals=[n for n in non_goals if n],
        quality_targets=quality_targets,
        runtime=RuntimeSpec(),
        source="fallback",
    )


def _contract_from_draft(
    draft: ContractDraft, base: ProjectContract
) -> ProjectContract:
    requirements: list[ContractRequirement] = []
    seen: set[str] = set()
    for idx, item in enumerate(draft.requirements, start=1):
        req_id = (item.id or f"R{idx}").strip().upper() or f"R{idx}"
        if req_id in seen:
            req_id = f"R{len(seen) + 1}"
        seen.add(req_id)
        requirements.append(
            ContractRequirement(
                id=req_id,
                description=item.description or item.id or f"Requirement {idx}",
                acceptance=[a for a in item.acceptance if a],
                priority=item.priority or "must",
            )
        )

    # The factory always needs a verifiable health requirement for smoke/deploy.
    if not any("health" in (r.description + " ".join(r.acceptance)).lower() for r in requirements):
        requirements.insert(
            0,
            ContractRequirement(
                id=_free_req_id(seen),
                description="Service exposes a working health endpoint",
                acceptance=["GET /health returns HTTP 200"],
            ),
        )

    return ProjectContract(
        goal=draft.goal or base.goal,
        users=draft.users,
        requirements=requirements,
        non_goals=draft.non_goals or base.non_goals,
        constraints=draft.constraints,
        quality_targets=draft.quality_targets or base.quality_targets,
        security_requirements=draft.security_requirements,
        runtime=base.runtime,
        source="architect",
    )


def _free_req_id(seen: set[str]) -> str:
    n = 1
    while f"R{n}" in seen:
        n += 1
    return f"R{n}"


def contract_from_planning(
    workspace,
    project: ProjectRow,
    context: dict,
    *,
    architect_output: str,
) -> tuple[ProjectContract, list[ArchitectureDecisionDraft]]:
    """Build the contract from architect output, falling back deterministically.

    Sources, in priority order: ``project-contract.json`` in the repo,
    the ``contract.json`` artifact, then a JSON block in the reply text.
    """
    base = fallback_contract(project, context)

    candidates: list[str] = []
    repo_file = workspace.repo_dir(project.id) / "project-contract.json"
    if repo_file.is_file():
        candidates.append(repo_file.read_text(encoding="utf-8", errors="replace"))
    if CONTRACT_ARTIFACT in workspace.list_artifacts(project.id):
        candidates.append(workspace.read_artifact(project.id, CONTRACT_ARTIFACT) or "")
    candidates.append(architect_output or "")

    for raw in candidates:
        draft = parse_agent_json(ContractDraft, raw)
        if draft and draft.requirements:
            contract = _contract_from_draft(draft, base)
            return contract, draft.decisions

    return base, []


# ---------------------------------------------------------------------------
# Artifacts / repo mirroring
# ---------------------------------------------------------------------------


def write_contract_artifacts(workspace, project_id: UUID, contract: ProjectContract) -> None:
    workspace.write_artifact(
        project_id,
        CONTRACT_ARTIFACT,
        json.dumps(contract.model_dump(), indent=2),
    )
    repo = workspace.repo_dir(project_id)
    try:
        if repo.is_dir():
            (repo / CONTRACT_REPO_FILE).write_text(contract.to_yaml(), encoding="utf-8")
    except Exception:
        logger.warning("Could not write %s into repo for %s", CONTRACT_REPO_FILE, project_id)


# ---------------------------------------------------------------------------
# Plan coverage
# ---------------------------------------------------------------------------

_STREAM_KEYWORDS = {
    "backend": ("api", "endpoint", "rest", "backend", "server", "database", "crud", "health"),
    "frontend": ("ui", "browser", "page", "screen", "frontend", "web", "form"),
}


def ensure_requirement_coverage(
    units: list[WorkUnit], contract: ProjectContract
) -> tuple[list[WorkUnit], dict]:
    """Map work units to requirement ids; add units for uncovered requirements.

    Planning cannot complete with an uncovered requirement — instead of failing
    and re-planning, the factory deterministically appends a dedicated work
    unit per uncovered requirement.
    """
    mapping: dict[str, list[str]] = {}
    covered: set[str] = set()

    for unit in units:
        text = f"{unit.title} {unit.description} {unit.feature_content or ''}".lower()
        matched: list[str] = []
        for req in contract.requirements:
            req_text = (req.description + " " + " ".join(req.acceptance)).lower()
            if req.id.lower() in text:
                matched.append(req.id)
                continue
            keywords = _STREAM_KEYWORDS.get(unit.stream, ())
            if keywords and any(k in req_text for k in keywords):
                matched.append(req.id)
                continue
            # Direct word overlap between requirement description and unit text.
            req_words = {w for w in req_text.split() if len(w) > 4}
            if req_words and sum(1 for w in req_words if w in text) >= 2:
                matched.append(req.id)
        if matched:
            mapping[unit.title] = matched
            covered.update(matched)

    added_units: list[str] = []
    result = list(units)
    for req in contract.requirements:
        if req.id in covered:
            continue
        acceptance = "\n".join(f"- {a}" for a in req.acceptance) or "- Works in the live preview"
        result.append(
            WorkUnit(
                stream="feature",
                title=f"Requirement {req.id}: {req.description[:48]}",
                description=(
                    f"Implement contract requirement **{req.id}**: {req.description}\n\n"
                    f"Acceptance criteria (write pytest tests named `test_{req.id.lower()}_*`):\n"
                    f"{acceptance}"
                ),
                feature_id=f"req-{req.id.lower()}",
                feature_content=f"{req.id}: {req.description}\n{acceptance}",
            )
        )
        added_units.append(req.id)
        covered.add(req.id)

    coverage = {
        "mapping": mapping,
        "covered": sorted(covered),
        "added_units": added_units,
        "total_requirements": len(contract.requirements),
    }
    return result, coverage


# Re-exported for stage code convenience.
async def sync_requirements_from_contract(session, project_id, contract) -> None:
    from app.services.evidence import sync_requirements_from_contract as _sync

    await _sync(session, project_id, contract)
