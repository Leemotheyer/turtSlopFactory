from app.artifacts.parsing import parse_agent_json
from app.artifacts.schemas import ContractDraft
from app.contract import ContractRequirement, ProjectContract
from app.db_models import ProjectRow
from app.services.contracts import ensure_requirement_coverage, fallback_contract
from app.services.work_planner import WorkUnit, plan_parallel_work


def _contract(reqs: list[tuple[str, str]]) -> ProjectContract:
    return ProjectContract(
        goal="test",
        requirements=[
            ContractRequirement(id=rid, description=desc, acceptance=["works"])
            for rid, desc in reqs
        ],
    )


def test_contract_yaml_roundtrip_keeps_healthcheck_compatible():
    contract = _contract([("R1", "Health endpoint"), ("R2", "Items API")])
    text = contract.to_yaml()
    # The preview spec loader scans for a healthcheck block with path/port.
    assert "healthcheck:" in text
    assert "path: /health" in text
    assert "port: 8080" in text

    parsed = ProjectContract.from_yaml(text)
    assert [r.id for r in parsed.requirements] == ["R1", "R2"]
    assert parsed.runtime.healthcheck_path == "/health"


def test_preview_spec_reads_contract_yaml(tmp_path):
    from app.services.preview_spec import load_preview_spec

    contract = _contract([("R1", "Health")])
    contract.runtime.healthcheck_path = "/status"
    contract.runtime.healthcheck_port = 9000
    (tmp_path / "project.contract.yaml").write_text(contract.to_yaml())

    spec = load_preview_spec(tmp_path)
    assert spec.path == "/status"
    assert spec.port == 9000


def test_fallback_contract_covers_health_api_ui():
    project = ProjectRow(name="Demo", description="An item tracker")
    contract = fallback_contract(project, {"notes": [], "intake": {}})
    ids = [r.id for r in contract.requirements]
    assert ids == ["R1", "R2", "R3"]
    assert all(r.acceptance for r in contract.requirements)


def test_fallback_contract_existing_repo_only_health():
    project = ProjectRow(name="Demo", description="Continue my repo")
    contract = fallback_contract(
        project, {"repo_analysis": {"has_existing_app": True}, "notes": []}
    )
    assert [r.id for r in contract.requirements] == ["R1"]


def test_coverage_adds_units_for_uncovered_requirements():
    contract = _contract(
        [
            ("R1", "Health endpoint returns ok"),
            ("R2", "REST API for items with crud endpoints"),
            ("R9", "Nightly export job writes zorbleflux summaries"),
        ]
    )
    units = plan_parallel_work([], "An item tracker api")
    covered_units, coverage = ensure_requirement_coverage(units, contract)

    # R9 matches nothing — a dedicated work unit is appended.
    assert "R9" in coverage["added_units"]
    assert any(u.feature_id == "req-r9" for u in covered_units)
    assert set(coverage["covered"]) == {"R1", "R2", "R9"}


def test_coverage_no_extra_units_when_all_covered():
    contract = _contract([("R1", "health endpoint"), ("R2", "api endpoints for items")])
    units = [
        WorkUnit(stream="backend", title="Backend API", description="routes and health"),
    ]
    covered_units, coverage = ensure_requirement_coverage(units, contract)
    assert coverage["added_units"] == []
    assert len(covered_units) == 1


def test_contract_draft_parses_from_fenced_reply():
    reply = """Here is the plan.

```json
{
  "goal": "Track invoices",
  "requirements": [
    {"id": "r1", "description": "Poll invoices", "acceptance": ["polls every 5 min"]},
    {"id": "R2", "description": "Expose health", "acceptance": ["GET /health 200"]}
  ],
  "decisions": [{"decision": "Use PostgreSQL", "reason": "transactional workload"}]
}
```
Done."""
    draft = parse_agent_json(ContractDraft, reply)
    assert draft is not None
    assert len(draft.requirements) == 2
    assert draft.decisions[0].decision == "Use PostgreSQL"


def test_requirement_id_normalized_uppercase():
    req = ContractRequirement(id="r7", description="x")
    assert req.id == "R7"
