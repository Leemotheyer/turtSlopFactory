#!/usr/bin/env python3
"""Agent evaluation harness: run benchmark projects through the full pipeline.

Each fixture in benchmarks/*.yaml describes a project spec and the expected
outcome (final state, verified requirements, artifacts, repo files). The
harness runs the real pipeline with the deterministic ``local`` backend and
no docker, so results are reproducible in CI — a regression here means the
factory itself got worse, independent of any LLM.

Usage:
    python scripts/run_benchmarks.py                 # all benchmarks
    python scripts/run_benchmarks.py greenfield-item-tracker
    python scripts/run_benchmarks.py --json          # machine-readable scorecard

Exit code is non-zero when any benchmark fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

# Environment must be pinned BEFORE the app is imported.
_WORKDIR = Path(tempfile.mkdtemp(prefix="factory-bench-"))
os.environ["WORKSPACE_ROOT"] = str(_WORKDIR / "workspaces")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_WORKDIR}/factory-bench.db"
os.environ["DISABLE_DOCKER"] = "1"
os.environ["AGENT_BACKEND"] = "local"
os.environ["WORKER_ENABLED"] = "false"
os.environ["DEPLOY_OBSERVATION_SECONDS"] = "0"
os.environ["AUTO_PROMOTE_TO_PRODUCTION"] = "false"

sys.path.insert(0, str(REPO_ROOT / "orchestrator"))

import yaml  # noqa: E402


def _load_fixtures(names: list[str] | None) -> list[dict]:
    fixtures = []
    for path in sorted(BENCHMARKS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("name"):
            continue
        if names and data["name"] not in names:
            continue
        fixtures.append(data)
    return fixtures


async def _prepare_database() -> None:
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import JSONB

    import app.db_models  # noqa: F401 — register tables before the JSONB swap
    from app.database import Base, init_db

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    await init_db()

    from app.database import SessionLocal
    from app.db_models import FactorySettingsRow

    async with SessionLocal() as session:
        settings_row = await session.get(FactorySettingsRow, 1)
        if settings_row is None:
            session.add(FactorySettingsRow(id=1, agent_backend="local", setup_complete=True))
            await session.commit()


async def _run_benchmark(fixture: dict) -> dict:
    from uuid import uuid4

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.db_models import PipelineRunRow, ProjectNoteRow, ProjectRow, RequirementRow
    from app.models import ProjectState
    from app.pipeline.executor import PipelineExecutor
    from app.services.contracts import get_latest_contract
    from app.workspace.manager import WorkspaceManager

    name = fixture["name"]
    expected = fixture.get("expected") or {}
    project_id = uuid4()
    workspace = WorkspaceManager()

    async with SessionLocal() as session:
        session.add(
            ProjectRow(
                id=project_id,
                name=name,
                description=fixture.get("description", "").strip(),
                state=ProjectState.PLANNING.value,
                max_enrichment_passes=int(fixture.get("max_enrichment_passes") or 0),
            )
        )
        for note in fixture.get("notes") or []:
            session.add(
                ProjectNoteRow(
                    project_id=project_id,
                    content=str(note.get("content") or ""),
                    note_type=str(note.get("type") or "instruction"),
                )
            )
        await session.commit()

    repo = workspace.repo_dir(project_id)
    for rel, content in (fixture.get("seed_repo_files") or {}).items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    executor = PipelineExecutor()
    started = time.monotonic()
    await asyncio.wait_for(executor.run_pipeline(project_id), timeout=900)
    duration = round(time.monotonic() - started, 1)

    problems: list[str] = []
    details: dict = {"duration_seconds": duration}

    async with SessionLocal() as session:
        project = await session.get(ProjectRow, project_id)
        details["final_state"] = project.state
        expected_state = expected.get("final_state")
        if expected_state and project.state != expected_state:
            problems.append(f"final state {project.state} != {expected_state}")

        requirements = (
            (await session.execute(
                select(RequirementRow).where(RequirementRow.project_id == project_id)
            )).scalars().all()
        )
        details["requirements"] = {r.req_id: r.status for r in requirements}
        min_reqs = int(expected.get("min_requirements") or 0)
        if len(requirements) < min_reqs:
            problems.append(f"only {len(requirements)} requirement(s), expected >= {min_reqs}")
        if expected.get("all_requirements_verified"):
            bad = [r.req_id for r in requirements if r.status not in ("verified", "waived")]
            if bad:
                problems.append(f"unverified requirement(s): {', '.join(bad)}")
        for keyword in expected.get("requirement_absent_keywords") or []:
            hits = [
                r.req_id for r in requirements if keyword.lower() in r.description.lower()
            ]
            if hits:
                problems.append(f"requirement mentioning '{keyword}' should not exist: {hits}")

        contract = await get_latest_contract(session, project_id)
        for keyword in expected.get("contract_non_goal_keywords") or []:
            if not contract or not any(
                keyword.lower() in goal.lower() for goal in contract.non_goals
            ):
                problems.append(f"contract non_goals missing '{keyword}'")

        runs = (
            (await session.execute(
                select(PipelineRunRow).where(PipelineRunRow.project_id == project_id)
            )).scalars().all()
        )
        if runs:
            details["outcome"] = runs[0].outcome
            details["fix_attempts"] = runs[0].fix_attempts
            details["human_interventions"] = runs[0].human_interventions

    artifacts = workspace.list_artifacts(project_id)
    for artifact in expected.get("artifacts") or []:
        if artifact not in artifacts:
            problems.append(f"missing artifact {artifact}")
    for rel in expected.get("repo_files") or []:
        if not (repo / rel).exists():
            problems.append(f"missing repo file {rel}")
    for pattern in expected.get("repo_globs") or []:
        if not list(repo.glob(pattern)):
            problems.append(f"no repo files match {pattern}")

    return {
        "name": name,
        "passed": not problems,
        "problems": problems,
        **details,
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="benchmark names to run (default: all)")
    parser.add_argument("--json", action="store_true", help="print machine-readable scorecard")
    args = parser.parse_args()

    fixtures = _load_fixtures(args.names or None)
    if not fixtures:
        print("No benchmarks matched.", file=sys.stderr)
        return 2

    await _prepare_database()

    results = []
    for fixture in fixtures:
        if not args.json:
            print(f"→ {fixture['name']} …", flush=True)
        try:
            result = await _run_benchmark(fixture)
        except Exception as exc:  # noqa: BLE001 — scorecard must survive one bad benchmark
            result = {"name": fixture["name"], "passed": False, "problems": [f"crashed: {exc}"]}
        results.append(result)
        if not args.json:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"  {status} ({result.get('duration_seconds', '?')}s) "
                  f"outcome={result.get('outcome')} fix_attempts={result.get('fix_attempts')}")
            for problem in result["problems"]:
                print(f"    ✗ {problem}")

    passed = sum(1 for r in results if r["passed"])
    scorecard = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
    if args.json:
        print(json.dumps(scorecard, indent=2))
    else:
        print(f"\n{passed}/{len(results)} benchmarks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
