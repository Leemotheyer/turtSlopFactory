"""Tests for intake-derived contracts and feature-completeness gating."""

from types import SimpleNamespace

from app.contract import ProjectContract, ContractRequirement
from app.db_models import ProjectRow
from app.services.contracts import fallback_contract
from app.services.feature_completeness import evaluate_feature_completeness
from app.services.intake_contract import (
    intake_capability_lines,
    intake_has_product_scope,
    minimum_enrichment_passes,
    requirements_from_intake,
)


def test_intake_capability_lines_splits_bullets():
    intake = {
        "must_have_features": "- Search manga catalog\n- Download chapters\n- Sonarr-like library UI",
        "success_criteria": "Users can add series and fetch new chapters automatically",
    }
    lines = intake_capability_lines(intake)
    assert intake_has_product_scope(intake)
    assert any("search" in line.lower() for line in lines)
    assert any("download" in line.lower() for line in lines)


def test_requirements_from_intake_use_r10_ids():
    intake = {"must_have_features": "Search catalog\nDownload chapters"}
    reqs = requirements_from_intake(intake)
    assert [r.id for r in reqs] == ["R10", "R11"]
    assert all(r.priority == "must" for r in reqs)


def test_fallback_contract_uses_intake_requirements_instead_of_generic_crud():
    project = ProjectRow(name="Manga", description="Manga downloader like Sonarr")
    contract = fallback_contract(
        project,
        {
            "intake": {
                "must_have_features": "Search and index manga\nDownload chapters automatically",
            },
            "notes": [],
        },
    )
    ids = [r.id for r in contract.requirements]
    assert ids[0] == "R1"
    assert "R10" in ids
    assert "R2" not in ids
    assert contract.source == "intake"


def test_fallback_contract_keeps_generic_crud_without_intake():
    project = ProjectRow(name="Demo", description="Item tracker")
    contract = fallback_contract(project, {"notes": [], "intake": {}})
    assert [r.id for r in contract.requirements] == ["R1", "R2", "R3"]


def test_minimum_enrichment_passes_respects_zero_config():
    intake = {"must_have_features": "Search\nDownload\nTrack library\nManage queue"}
    assert minimum_enrichment_passes(intake, configured_max=0) == 0
    assert minimum_enrichment_passes(intake, configured_max=4) >= 1


def test_feature_completeness_blocks_unverified_intake_requirements():
    contract = ProjectContract(
        goal="Manga app",
        requirements=[
            ContractRequirement(id="R1", description="health", acceptance=["ok"], priority="must"),
            ContractRequirement(
                id="R10",
                description="Search manga",
                acceptance=["search works"],
                priority="must",
            ),
        ],
        source="intake",
    )
    acceptance = {
        "requirements": {
            "R1": {"status": "verified"},
            "R10": {"status": "unverified"},
        }
    }
    context = {
        "intake": {"must_have_features": "Search manga catalog"},
        "max_enrichment_passes": 4,
        "enrichment_passes_completed": 0,
        "product_qa_passed": False,
    }
    report = evaluate_feature_completeness(
        contract, context, acceptance, workspace=None, project_id=None
    )
    assert report["passed"] is False
    assert any("R10" in issue for issue in report["issues"])
