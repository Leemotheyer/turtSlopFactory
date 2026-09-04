"""Feature-completeness gate: block production-ready until intake scope is delivered."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.config import settings
from app.contract import ProjectContract
from app.services.intake_contract import (
    intake_has_product_scope,
    minimum_enrichment_passes,
    requirements_from_intake,
)

if TYPE_CHECKING:
    from app.workspace.manager import WorkspaceManager


def must_requirements(contract: ProjectContract) -> list:
    """Requirements that block acceptance when unverified."""
    must = [r for r in contract.requirements if r.priority == "must"]
    if must:
        return must
    # Legacy / benchmark contracts without explicit priority — every row counts.
    return list(contract.requirements)


def intake_must_requirements(contract: ProjectContract, intake: dict | None) -> list:
    """Intake-derived requirements (R10+) that must be verified."""
    ids = {r.id for r in requirements_from_intake(intake)}
    return [r for r in contract.requirements if r.id in ids]


def _read_product_qa_passed(workspace: "WorkspaceManager", project_id: UUID, context: dict) -> bool:
    if context.get("product_qa_passed") is True:
        return True
    if "product-qa.json" not in workspace.list_artifacts(project_id):
        return False
    try:
        raw = workspace.read_artifact(project_id, "product-qa.json") or "{}"
        data = json.loads(raw)
        return bool(data.get("passed"))
    except (json.JSONDecodeError, TypeError):
        return False


def evaluate_feature_completeness(
    contract: ProjectContract,
    context: dict,
    acceptance_report: dict | None,
    *,
    workspace: "WorkspaceManager | None" = None,
    project_id: UUID | None = None,
) -> dict[str, Any]:
    """Decide whether the build is feature-complete vs scaffold-complete."""
    intake = context.get("intake") or {}
    acceptance_report = acceptance_report or {}
    req_status = acceptance_report.get("requirements") or {}

    issues: list[str] = []
    intake_scope = intake_has_product_scope(intake)

    if intake_scope:
        intake_reqs = intake_must_requirements(contract, intake)
        if not intake_reqs:
            # Contract was not expanded from intake — treat as incomplete planning.
            issues.append(
                "Intake describes product capabilities but the contract has no intake-derived "
                "requirements (expected R10+). Re-run planning or edit the contract."
            )
        for req in intake_reqs:
            entry = req_status.get(req.id) or {}
            status = entry.get("status", "unverified")
            if status not in ("verified", "waived"):
                issues.append(
                    f"{req.id} [{status}] not delivered: {req.description[:120]}"
                )

        configured_max = int(
            context.get("max_enrichment_passes")
            if context.get("max_enrichment_passes") is not None
            else settings.max_enrichment_passes
        )
        min_passes = minimum_enrichment_passes(intake, configured_max=configured_max)
        passes_done = int(context.get("enrichment_passes_completed") or 0)
        if context.get("post_smoke_enrichment_complete"):
            passes_done = max(passes_done, passes_done + 1)
        if min_passes > 0 and passes_done < min_passes:
            issues.append(
                f"Enrichment incomplete ({passes_done}/{min_passes} required passes) — "
                "the factory must iterate on core flows before production review"
            )

        qa_ok = _read_product_qa_passed(workspace, project_id, context) if workspace and project_id else context.get("product_qa_passed")
        if not qa_ok:
            issues.append(
                "Product QA has not passed on the live preview — core intake capabilities "
                "must be demonstrable, not just covered by scaffold tests"
            )

        # Scaffold-only green check: generic CRUD scaffold must not be the only proof.
        scaffold_verified = sum(
            1
            for rid, entry in req_status.items()
            if rid in {"R2", "R3"} and entry.get("status") == "verified"
        )
        intake_verified = sum(
            1
            for req in intake_reqs
            if (req_status.get(req.id) or {}).get("status") == "verified"
        )
        if scaffold_verified >= 2 and intake_verified == 0 and intake_reqs:
            issues.append(
                "Only the factory scaffold (generic CRUD/UI) is verified — none of the "
                "intake capabilities have passing evidence yet"
            )

    passed = len(issues) == 0
    return {
        "passed": passed,
        "intake_scope": intake_scope,
        "issues": issues,
        "enrichment_passes_completed": int(context.get("enrichment_passes_completed") or 0),
        "minimum_enrichment_passes": minimum_enrichment_passes(
            intake,
            configured_max=int(
                context.get("max_enrichment_passes")
                if context.get("max_enrichment_passes") is not None
                else settings.max_enrichment_passes
            ),
        ),
        "product_qa_passed": _read_product_qa_passed(workspace, project_id, context)
        if workspace and project_id
        else bool(context.get("product_qa_passed")),
    }
