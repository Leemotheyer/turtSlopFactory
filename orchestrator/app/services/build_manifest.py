"""Reproducibility: build manifests capturing everything behind a build.

Answers "why did build #183 work but #184 fail" — records commit, agent
backend/model, prompt versions, contract version, and dependency hashes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import datetime
from uuid import UUID

logger = logging.getLogger(__name__)

BUILD_MANIFEST_ARTIFACT = "build-manifest.json"


def _git_commit(repo) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _file_sha256(path) -> str | None:
    try:
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


async def write_build_manifest(
    workspace,
    session,
    project,
    *,
    build_id: str,
    image_tag: str,
) -> dict:
    from app.agents.prompt_builder import prompt_versions
    from app.services.contracts import get_latest_contract
    from app.services.factory_settings import get_agent_backend, get_agent_models

    repo = workspace.repo_dir(project.id)

    try:
        backend = await get_agent_backend(session)
    except Exception:
        backend = "unknown"
    try:
        models = await get_agent_models(session)
    except Exception:
        models = {}
    try:
        contract = await get_latest_contract(session, project.id)
        contract_version = contract.version if contract else None
    except Exception:
        contract_version = None

    manifest = {
        "build_id": build_id,
        "image_tag": image_tag,
        "created_at": datetime.utcnow().isoformat(),
        "git_commit": _git_commit(repo),
        "branch": project.work_branch or project.branch,
        "agent_backend": backend,
        "agent_models": models,
        "prompt_versions": prompt_versions(),
        "contract_version": contract_version,
        "requirements_txt_sha256": _file_sha256(repo / "requirements.txt"),
        "dockerfile_sha256": _file_sha256(repo / "Dockerfile"),
        "factory_version": "1.0.0",
    }

    try:
        workspace.write_artifact(
            project.id, BUILD_MANIFEST_ARTIFACT, json.dumps(manifest, indent=2)
        )
        workspace.write_artifact(
            project.id, f"build-manifest-{build_id}.json", json.dumps(manifest, indent=2)
        )
    except Exception:
        logger.warning("Could not write build manifest for %s", project.id)
    return manifest


def manifest_for_build(workspace, project_id: UUID, build_id: str) -> dict | None:
    name = f"build-manifest-{build_id}.json"
    if name not in workspace.list_artifacts(project_id):
        return None
    try:
        return json.loads(workspace.read_artifact(project_id, name) or "{}")
    except Exception:
        return None
