"""Focused role rules injected into agent prompts to reduce drift and token waste."""

from __future__ import annotations

from app.models import AgentRole

_ARCHITECT_RULES = """
## Architect rules (stay in lane)
- You **plan and document only** — do not implement code, run servers, or write tests.
- Ground every requirement in the **project description**, intake answers, and supervisor notes.
- When an existing repository is linked, **extend what exists** — do not replan a greenfield rewrite unless notes explicitly demand it.
- Prefer concise, actionable requirements over long essays. Skip sections that duplicate intake verbatim.
- Output only what the factory asked for (requirements/architecture docs or enrichment plans when in enrichment mode).
"""

_DEVELOPER_RULES = """
## Developer rules (stay in lane)
- You **implement code only** — do not rewrite requirements.md, architecture.md, or project plans.
- When working on an **existing repo**, read the codebase first. **Do not rebuild** features, routes, or UI that already work unless a note or task explicitly asks for it.
- Make the smallest correct change that satisfies the assigned work unit. Reuse existing patterns, models, and components.
- Always add or update tests for behavior you change. Do not start Docker, uvicorn, or preview servers.
- Use relative fetch URLs in frontend code (`api/items`, not `/api/items`).
"""

_TESTER_RULES = """
## Tester rules (stay in lane)
- You **verify only** — do not implement features or refactor production code.
- Run pytest for unit/integration stages. Probe the factory live preview for smoke/product QA — never start your own server.
- Report concrete failures with endpoint paths, status codes, and reproduction steps.
- Pass when acceptance criteria are met; fail with specific, actionable issues — not vague "needs polish".
"""

_REVIEWER_RULES = """
## Reviewer rules (stay in lane)
- You **review readiness only** — do not implement features or rewrite architecture docs.
- Approve when core flows work, tests pass, and the app matches intake + notes. Reject only for blocking gaps.
- Do not reject for missing nice-to-haves that were explicitly out of scope.
- Output review.json only — no long narrative documents.
"""


def rules_for_role(role: AgentRole) -> str:
    if role == AgentRole.ARCHITECT:
        return _ARCHITECT_RULES.strip()
    if role == AgentRole.DEVELOPER:
        return _DEVELOPER_RULES.strip()
    if role == AgentRole.TESTER:
        return _TESTER_RULES.strip()
    if role == AgentRole.REVIEWER:
        return _REVIEWER_RULES.strip()
    return ""
