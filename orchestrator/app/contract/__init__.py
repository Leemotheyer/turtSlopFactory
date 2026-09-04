"""Project Contract: the structured, executable unit of work.

A contract turns a free-text project description into requirements with
explicit acceptance criteria — the externally defined meaning of "good" that
the acceptance evaluator, adversary, and reviewer all bind to.
"""

from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_REQ_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")


class ContractRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    description: str
    acceptance: list[str] = Field(default_factory=list)
    priority: str = "must"  # must | should | could

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, value: str) -> str:
        value = str(value).strip().upper()
        if not _REQ_ID_RE.match(value):
            value = re.sub(r"[^A-Z0-9_-]", "", value)[:16] or "R0"
        return value


class RuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "fastapi"  # declared runtime; the factory preview currently runs uvicorn ASGI apps
    healthcheck_path: str = "/health"
    healthcheck_port: int = 8080


class ProjectContract(BaseModel):
    model_config = ConfigDict(extra="ignore")

    goal: str = ""
    users: list[str] = Field(default_factory=list)
    requirements: list[ContractRequirement] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    quality_targets: list[str] = Field(default_factory=list)
    security_requirements: list[str] = Field(default_factory=list)
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    version: int = 1
    source: str = "fallback"  # architect | fallback | human

    def requirement_ids(self) -> list[str]:
        return [req.id for req in self.requirements]

    def get_requirement(self, req_id: str) -> ContractRequirement | None:
        target = str(req_id).strip().upper()
        for req in self.requirements:
            if req.id == target:
                return req
        return None

    def to_yaml(self) -> str:
        """Serialize for the repo copy (``project.contract.yaml``).

        Keeps a ``deployment.healthcheck`` block compatible with the preview
        spec loader so the contract is the single source for health probing.
        """
        payload = {
            "goal": self.goal,
            "users": self.users,
            "requirements": [
                {
                    "id": req.id,
                    "description": req.description,
                    "acceptance": req.acceptance,
                    "priority": req.priority,
                }
                for req in self.requirements
            ],
            "non_goals": self.non_goals,
            "constraints": self.constraints,
            "quality_targets": self.quality_targets,
            "security_requirements": self.security_requirements,
            "runtime": {"type": self.runtime.type},
            "deployment": {
                "healthcheck": {
                    "type": "http",
                    "path": self.runtime.healthcheck_path,
                    "port": self.runtime.healthcheck_port,
                }
            },
            "contract_version": self.version,
            "source": self.source,
        }
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, text: str) -> "ProjectContract":
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            data = {}
        healthcheck = ((data.get("deployment") or {}).get("healthcheck")) or {}
        runtime = data.get("runtime") or {}
        return cls(
            goal=str(data.get("goal") or ""),
            users=[str(u) for u in data.get("users") or []],
            requirements=[
                ContractRequirement.model_validate(req)
                for req in data.get("requirements") or []
                if isinstance(req, dict) and req.get("id")
            ],
            non_goals=[str(x) for x in data.get("non_goals") or []],
            constraints=[str(x) for x in data.get("constraints") or []],
            quality_targets=[str(x) for x in data.get("quality_targets") or []],
            security_requirements=[str(x) for x in data.get("security_requirements") or []],
            runtime=RuntimeSpec(
                type=str(runtime.get("type") or "fastapi"),
                healthcheck_path=str(healthcheck.get("path") or "/health"),
                healthcheck_port=int(healthcheck.get("port") or 8080),
            ),
            version=int(data.get("contract_version") or 1),
            source=str(data.get("source") or "fallback"),
        )
