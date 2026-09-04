"""Role lane rules, loaded from versioned prompt files (see app/agents/prompts/)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.models import AgentRole

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@lru_cache(maxsize=16)
def rules_for_role(role: AgentRole) -> str:
    path = _PROMPTS_DIR / role.value / "rules.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
