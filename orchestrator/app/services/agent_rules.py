"""User-defined agent rules — global (factory-wide) and per-project."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import ProjectRow

AGENT_RULES_MAX = 10000


def normalize_agent_rules(text: str | None) -> str:
    if not text:
        return ""
    return text.strip()[:AGENT_RULES_MAX]


def append_agent_rules_sections(sections: list[str], context: dict) -> None:
    """Inject global and project rule blocks into a prompt section list."""
    global_rules = normalize_agent_rules(context.get("global_agent_rules"))
    project_rules = normalize_agent_rules(context.get("project_agent_rules"))

    if global_rules:
        sections.append(
            "\n## Global user rules (always apply to every project)\n"
            "Factory-wide constraints set by the user. Follow them unless a supervisor note "
            "explicitly overrides for this task."
        )
        sections.extend(_format_rule_lines(global_rules))

    if project_rules:
        sections.append(
            "\n## Project rules (always apply to this project)\n"
            "Persistent rules for this project only. Follow them unless a supervisor note "
            "explicitly overrides."
        )
        sections.extend(_format_rule_lines(project_rules))


def format_rules_for_markdown(title: str, rules_text: str) -> str:
    text = normalize_agent_rules(rules_text)
    if not text:
        return ""
    lines = [f"## {title}", ""]
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ", "• ")):
            lines.append(stripped)
        else:
            lines.append(f"- {stripped}")
    lines.append("")
    return "\n".join(lines)


def combined_rules_text(global_rules: str, project_rules: str) -> str:
    parts: list[str] = []
    if normalize_agent_rules(global_rules):
        parts.append(format_rules_for_markdown("Global factory rules", global_rules))
    if normalize_agent_rules(project_rules):
        parts.append(format_rules_for_markdown("Project rules", project_rules))
    return "\n".join(parts).strip()


def _format_rule_lines(rules_text: str) -> list[str]:
    lines: list[str] = []
    for raw in rules_text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        content = stripped.lstrip("-•* ").strip()
        if content:
            lines.append(f"- {content}")
    return lines


async def get_global_agent_rules(session: AsyncSession) -> str:
    from app.services.factory_settings import get_or_create_settings_row

    row = await get_or_create_settings_row(session)
    return normalize_agent_rules(getattr(row, "global_agent_rules", None))


async def set_global_agent_rules(session: AsyncSession, rules: str | None) -> str:
    from app.services.factory_settings import get_or_create_settings_row

    row = await get_or_create_settings_row(session)
    row.global_agent_rules = normalize_agent_rules(rules) or None
    await session.commit()
    return normalize_agent_rules(row.global_agent_rules)


async def load_rules_context(session: AsyncSession, project: ProjectRow) -> dict[str, str]:
    return {
        "global_agent_rules": await get_global_agent_rules(session),
        "project_agent_rules": normalize_agent_rules(getattr(project, "agent_rules", None)),
    }
