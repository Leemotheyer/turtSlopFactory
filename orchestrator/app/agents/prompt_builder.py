"""Assemble Cursor agent prompts from versioned template files + pipeline context.

Templates live in ``app/agents/prompts/<role>/`` (``rules.md``, ``VERSION``,
``tasks/*.md``) and are versioned like code: bump ``VERSION`` when a prompt
changes so runs record which prompt produced which result.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template

from app.agents.rules import rules_for_role
from app.config import settings
from app.models import AgentRole
from app.services.agent_rules import append_agent_rules_sections
from app.services.memory import format_memory_for_prompt
from app.services.product_enrichment import enrichment_pass_theme_hint
from app.services.repo_analysis import format_repo_analysis_compact, format_repo_analysis_for_prompt

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Profiles control which context blocks each invocation receives.
PROFILE_DEVELOPER_FIX = "developer_fix"
PROFILE_DEVELOPER_FEATURE = "developer_feature"
PROFILE_DEVELOPER_FULL = "developer_full"
PROFILE_ARCHITECT_ENRICHMENT = "architect_enrichment"
PROFILE_ARCHITECT_PLANNING = "architect_planning"
PROFILE_TESTER_LIGHT = "tester_light"
PROFILE_TESTER_FULL = "tester_full"
PROFILE_REVIEWER = "reviewer"
PROFILE_ADVERSARY = "adversary"


@lru_cache(maxsize=64)
def _load_task_template(role: str, name: str) -> Template:
    path = PROMPTS_DIR / role / "tasks" / f"{name}.md"
    return Template(path.read_text(encoding="utf-8"))


def _render(role: AgentRole, name: str, **values) -> str:
    return _load_task_template(role.value, name).safe_substitute(**values).strip()


@lru_cache(maxsize=16)
def prompt_version_for_role(role: AgentRole) -> str:
    path = PROMPTS_DIR / role.value / "VERSION"
    try:
        version = path.read_text(encoding="utf-8").strip() or "0"
    except OSError:
        version = "0"
    return f"{role.value}-v{version}"


def prompt_versions() -> dict[str, str]:
    return {role.value: prompt_version_for_role(role) for role in AgentRole}


def _is_focused_developer(context: dict) -> bool:
    return bool(
        context.get("work_stream")
        or context.get("enrichment_command")
        or context.get("prompt_focus") == "fix"
        or (context.get("incremental") and context.get("last_failure"))
    )


def _resolve_profile(role: AgentRole, context: dict) -> str:
    if role == AgentRole.DEVELOPER:
        if context.get("prompt_focus") == "fix" or (
            context.get("incremental") and (context.get("fix_brief") or context.get("last_failure"))
        ):
            return PROFILE_DEVELOPER_FIX
        if _is_focused_developer(context):
            return PROFILE_DEVELOPER_FEATURE
        return PROFILE_DEVELOPER_FULL
    if role == AgentRole.ARCHITECT:
        if context.get("enrichment_pass"):
            return PROFILE_ARCHITECT_ENRICHMENT
        return PROFILE_ARCHITECT_PLANNING
    if role == AgentRole.TESTER:
        if context.get("test_stage") in ("write_acceptance", "user_perspective_review"):
            return PROFILE_TESTER_FULL
        return PROFILE_TESTER_LIGHT
    if role == AgentRole.REVIEWER:
        return PROFILE_REVIEWER
    if role == AgentRole.ADVERSARY:
        return PROFILE_ADVERSARY
    return "full"


def _contract_section(context: dict, *, mode: str = "full") -> str:
    contract = context.get("contract")
    if not contract:
        return ""
    goal = getattr(contract, "goal", "") or ""
    requirements = getattr(contract, "requirements", []) or []
    must = [r for r in requirements if getattr(r, "priority", None) == "must"] or requirements

    if mode == "summary":
        lines = ["\n## Contract summary"]
        if goal:
            lines.append(goal[:300])
        for req in must[:10]:
            lines.append(f"- **{req.id}**: {req.description[:120]}")
        return "\n".join(lines)

    if mode == "compact":
        lines = ["\n## Contract (definition of done)"]
        if goal:
            lines.append(goal[:300])
        for req in must[:8]:
            lines.append(f"- **{req.id}**: {req.description[:160]}")
            criteria = getattr(req, "acceptance", None) or []
            if criteria:
                lines.append(f"  - accept: {criteria[0][:120]}")
        return "\n".join(lines)

    lines = ["\n## Project contract (the definition of done)"]
    if goal:
        lines.append(f"Goal: {goal[:500]}")
    for req in requirements[:12]:
        lines.append(f"- **{req.id}** ({req.priority}): {req.description}")
        for criterion in req.acceptance[:4]:
            lines.append(f"  - accept: {criterion}")
    non_goals = getattr(contract, "non_goals", None) or []
    if non_goals:
        lines.append("Non-goals: " + "; ".join(str(n) for n in non_goals[:6]))
    lines.append(
        "Verification: name pytest tests `test_<req_id_lowercase>_*` for requirement evidence."
    )
    return "\n".join(lines)


def _intake_capability_section(intake: dict, *, limit: int = 15) -> str:
    from app.services.intake_contract import intake_capability_lines

    lines = intake_capability_lines(intake)
    if not lines:
        return ""
    return "\n## Intake capabilities\n" + "\n".join(f"- {line}" for line in lines[:limit])


def _compact_preview_section(context: dict) -> str:
    health_path = context.get("preview_health_path") or "/health"
    preview_port = context.get("preview_app_port") or 8080
    return (
        f"\n## Live preview\n"
        f"- Factory-managed — do not start servers\n"
        f"- `0.0.0.0:{preview_port}`; `GET {health_path}` → 200 `{{\"status\": \"ok\"}}`\n"
        f"- UI: relative `fetch('api/...')` URLs"
    )


def _full_preview_section(context: dict) -> str:
    preview_url = context.get("preview_url") or ""
    preview_status = context.get("preview_status") or "not started"
    health_path = context.get("preview_health_path") or "/health"
    preview_port = context.get("preview_app_port") or 8080
    return f"""
## Live preview (factory-managed)
You must NOT run `docker`, `docker compose`, `docker run`, `uvicorn`, or other servers.

- URL: {preview_url or "(published after deploy)"} | status: {preview_status}
- Listen on `0.0.0.0:{preview_port}`; `GET {health_path}` → 200 `{{"status": "ok"}}`
- Use relative `fetch('api/...')` URLs — not `/api/...`
"""


def _header(role: AgentRole, name: str, *, compact: bool = False) -> list[str]:
    if compact:
        return [f"**{role.value}** agent — project **{name}**"]
    return [
        f"You are the **{role.value}** agent for the turtSlopFactory software pipeline.",
        f"Project: **{name}**",
        rules_for_role(role),
    ]


def _append_notes(sections: list[str], notes: list[dict], *, limit: int = 8) -> None:
    if not notes:
        return
    sections.append("\n## Supervisor notes")
    for note in notes[:limit]:
        label = note.get("type", "note").replace("_", " ").title()
        sections.append(f"- [{label}] {note.get('content', '')}")


def _append_git_workflow(sections: list[str], context: dict) -> None:
    if not context.get("isolate_branch") or not context.get("work_branch"):
        return
    base = context.get("base_branch", "main")
    work = context["work_branch"]
    sections.append(
        f"\n## Git\n- Production: `{base}` (do not commit)\n- Work branch: `{work}`"
    )


def _append_developer_task(sections: list[str], context: dict, existing_note: str) -> None:
    stream = context.get("work_stream")
    if stream == "backend":
        sections.append("\n" + _render(AgentRole.DEVELOPER, "backend", existing_note=existing_note))
    elif stream == "frontend":
        sections.append("\n" + _render(AgentRole.DEVELOPER, "frontend", existing_note=existing_note))
    elif stream == "feature":
        enrichment_block = ""
        if context.get("enrichment_command"):
            enrichment_block = _render(AgentRole.DEVELOPER, "enrichment_developer_mode") + "\n"
            if context.get("enrichment_require_substantial_changes"):
                enrichment_block += (
                    "\n## Shallow attempt rejected\n"
                    "Implement real code (backend, frontend, tests) — not a plan or summary.\n"
                )
            if context.get("enrichment_tier") == "milestone":
                enrichment_block += _render(AgentRole.DEVELOPER, "enrichment_milestone_block")
            else:
                enrichment_block += _render(AgentRole.DEVELOPER, "enrichment_block")
        sections.append(
            "\n"
            + _render(
                AgentRole.DEVELOPER,
                "feature",
                feature_id=context.get("feature_id") or "feature",
                content=context.get("feature_content") or context.get("work_description", ""),
                existing_note=existing_note,
                enrichment_block=enrichment_block,
            )
        )
    else:
        sections.append("\n" + _render(AgentRole.DEVELOPER, "full", existing_note=existing_note))


def _append_developer_fix(sections: list[str], context: dict) -> None:
    failure_text = context.get("fix_brief") or context.get("last_failure") or ""
    sections.append(f"\n## Fix failure\n{str(failure_text)[:1500]}")
    focus = context.get("fix_focus")
    if focus and focus != "general":
        sections.append(f"Priority: **{focus}**")
    regression_hint = context.get("regression_test_hint")
    if regression_hint:
        sections.append(
            f"Add regression test `tests/regression/{regression_hint}` — do not modify existing tests."
        )


def _append_enrichment_architect(sections: list[str], context: dict, intake: dict) -> None:
    enrichment_pass = context.get("enrichment_pass")
    audit = context.get("preview_audit") or {}
    max_features = context.get("max_features_per_pass", 8)
    max_milestones = int(context.get("max_milestones_per_pass") or 1)
    max_polish = max(0, int(max_features) - max_milestones)
    if max_milestones > 1:
        milestone_rule = (
            'Include **one or two** `tier: "milestone"` features — substantial new capabilities.'
        )
        milestone_count_rule = f"Propose **one or two milestones** plus up to **{max_polish}** polish"
    else:
        milestone_rule = 'Include **exactly one** `tier: "milestone"` feature — a major expansion.'
        milestone_count_rule = f"Propose **one milestone** plus up to **{max_polish}** polish"
    theme_hint = enrichment_pass_theme_hint(
        int(enrichment_pass),
        int(context.get("improvement_cycle_number") or 1),
    )
    sections.append(
        "\n"
        + _render(
            AgentRole.ARCHITECT,
            "enrichment",
            enrichment_pass=enrichment_pass,
            max_passes=context.get("max_enrichment_passes", 4),
            theme_hint=theme_hint,
            audit_health_ok=audit.get("health_ok", False),
            audit_has_html_ui=audit.get("has_html_ui", False),
            audit_issues=", ".join(audit.get("issues") or []) or "none",
            max_features=max_features,
            max_polish=max_polish,
            milestone_rule=milestone_rule,
            milestone_count_rule=milestone_count_rule,
        )
    )
    intake_block = _intake_capability_section(intake, limit=12)
    if intake_block:
        sections.append(intake_block)
    ux_backlog = context.get("improvement_backlog") or context.get("ux_improvement_backlog") or []
    if ux_backlog:
        sections.append(
            "\n## Prior review ideas\n"
            + "\n".join(
                f"- {item.get('title', 'Improvement')}: {str(item.get('description', ''))[:100]}"
                for item in ux_backlog[:10]
                if isinstance(item, dict)
            )
        )
    qa_feedback = context.get("product_qa_feedback") or {}
    qa_issues = [str(i).strip() for i in (qa_feedback.get("issues") or []) if str(i).strip()]
    qa_suggested = [
        str(s).strip() for s in (qa_feedback.get("suggested_features") or []) if str(s).strip()
    ]
    if qa_issues or qa_suggested:
        sections.append(
            "\n## Product QA (fix first)\n"
            + "\n".join(f"- {issue}" for issue in qa_issues[:8])
            + (
                "\n" + "\n".join(f"- {s}" for s in qa_suggested[:6])
                if qa_suggested
                else ""
            )
        )


def _build_developer_fix_prompt(context: dict) -> str:
    name = context.get("name", "app")
    intake = context.get("intake") or {}
    sections = _header(AgentRole.DEVELOPER, name, compact=True)
    append_agent_rules_sections(sections, context, compact=True)
    if intake:
        intake_block = _intake_capability_section(intake, limit=12)
        if intake_block:
            sections.append(intake_block)
    sections.append(_compact_preview_section(context))
    _append_developer_fix(sections, context)
    _append_git_workflow(sections, context)
    return "\n".join(sections).strip()


def _build_developer_feature_prompt(context: dict) -> str:
    name = context.get("name", "app")
    intake = context.get("intake") or {}
    existing_note = ""
    if context.get("repo_analysis", {}).get("has_existing_app"):
        existing_note = "\nExtend existing code — do not rebuild working routes/UI.\n"
    sections = _header(AgentRole.DEVELOPER, name, compact=True)
    append_agent_rules_sections(sections, context, compact=True)
    repo_block = format_repo_analysis_compact(context.get("repo_analysis"))
    if repo_block:
        sections.append(f"\n{repo_block}")
    if intake:
        intake_block = _intake_capability_section(intake, limit=10)
        if intake_block:
            sections.append(intake_block)
    _append_notes(sections, context.get("notes", []), limit=5)
    sections.append(_compact_preview_section(context))
    _append_developer_task(sections, context, existing_note)
    if context.get("incremental") and (context.get("fix_brief") or context.get("last_failure")):
        _append_developer_fix(sections, context)
    _append_git_workflow(sections, context)
    return "\n".join(sections).strip()


def _build_developer_full_prompt(context: dict) -> str:
    name = context.get("name", "app")
    description = context.get("description", "")
    original = context.get("original_description") or description
    intake = context.get("intake") or {}
    existing_note = ""
    if context.get("repo_analysis", {}).get("has_existing_app"):
        existing_note = """
## Existing codebase
Extend the current implementation. **Do not rebuild** working routes, models, or UI unless this task explicitly says to replace them.
"""
    sections = _header(AgentRole.DEVELOPER, name)
    append_agent_rules_sections(sections, context)
    sections.append(f"\n## Product vision\n{original.strip()}")
    if description.strip() and description.strip() != original.strip():
        sections.append(f"\n## Refined spec\n{description.strip()}")
    contract_block = _contract_section(context, mode="compact")
    if contract_block:
        sections.append(contract_block)
    repo_block = format_repo_analysis_for_prompt(context.get("repo_analysis"))
    if repo_block:
        sections.append(f"\n{repo_block}")
    memory_block = format_memory_for_prompt(context.get("project_memory"))
    if memory_block:
        sections.append(memory_block)
    if intake:
        sections.append("\n## Intake")
        for key, val in intake.items():
            if isinstance(val, list):
                val = ", ".join(val)
            sections.append(f"- {key.replace('_', ' ').title()}: {val}")
    _append_notes(sections, context.get("notes", []))
    sections.append(_full_preview_section(context))
    _append_developer_task(sections, context, existing_note)
    if context.get("incremental") and (context.get("fix_brief") or context.get("last_failure")):
        _append_developer_fix(sections, context)
    _append_git_workflow(sections, context)
    return "\n".join(sections).strip()


def _build_architect_enrichment_prompt(context: dict) -> str:
    name = context.get("name", "app")
    description = context.get("description", "")[:600]
    intake = context.get("intake") or {}
    sections = _header(AgentRole.ARCHITECT, name, compact=True)
    append_agent_rules_sections(sections, context, compact=True)
    if description:
        sections.append(f"\n## Product\n{description}")
    if context.get("last_failure"):
        sections.append(f"\n## Previous failure\n{str(context['last_failure'])[:2000]}")
    _append_enrichment_architect(sections, context, intake)
    sections.append(
        "\n## Task\nOutput `enrichment-plan.json` — substantial in-scope improvements only."
    )
    return "\n".join(sections).strip()


def _build_architect_planning_prompt(context: dict) -> str:
    name = context.get("name", "app")
    description = context.get("description", "")
    original = context.get("original_description") or description
    intake = context.get("intake") or {}
    sections = _header(AgentRole.ARCHITECT, name)
    append_agent_rules_sections(sections, context)
    sections.append(f"\n## Product vision\n{original.strip()}")
    if description.strip() and description.strip() != original.strip():
        sections.append(f"\n## Refined spec\n{description.strip()}")
    repo_block = (
        format_repo_analysis_compact(context.get("repo_analysis"))
        if context.get("repo_analysis", {}).get("has_existing_app")
        else format_repo_analysis_for_prompt(context.get("repo_analysis"))
    )
    if repo_block:
        sections.append(f"\n{repo_block}")
    memory_block = format_memory_for_prompt(context.get("project_memory"))
    if memory_block:
        sections.append(memory_block)
    if context.get("git_history") and context.get("repo_url"):
        sections.append(
            "\n## Recent git history\n```\n" + str(context["git_history"])[:800] + "\n```"
        )
    if intake:
        sections.append("\n## Intake")
        for key, val in list(intake.items())[:12]:
            if isinstance(val, list):
                val = ", ".join(val)
            sections.append(f"- {key.replace('_', ' ').title()}: {val}")
    _append_notes(sections, context.get("notes", []))
    if context.get("loose_plan"):
        sections.append("\n## Discovery\nSee discovery-plan.md in artifacts.")
    if context.get("input_responses"):
        sections.append("\n## Supervisor decisions")
        for resp in context.get("input_responses", [])[:8]:
            decision = resp.get("resolved_decision") or resp.get("default_decision", "")
            sections.append(f"- {resp.get('question', '')} → {decision}")
    if context.get("last_failure"):
        sections.append(f"\n## Previous failure\n{str(context['last_failure'])[:3000]}")
    draft = context.get("requirements_draft")
    if draft:
        sections.append(
            f"\n## Requirements draft (refine — do not ignore)\n{draft[:4500]}"
        )
    min_reqs = int(context.get("initial_min_requirements") or settings.initial_min_requirements)
    task = "plan_repo" if context.get("repo_url") else "plan_no_repo"
    sections.append("\n" + _render(AgentRole.ARCHITECT, task, min_requirements=min_reqs))
    sections.append(_compact_preview_section(context))
    return "\n".join(sections).strip()


def _build_tester_light_prompt(context: dict) -> str:
    name = context.get("name", "app")
    upstream = context.get("preview_upstream") or context.get("preview_url") or ""
    health_path = context.get("preview_health_path") or "/health"
    stage = context.get("test_stage", "unit")
    sections = _header(AgentRole.TESTER, name, compact=True)
    if stage == "product_qa":
        audit = context.get("preview_audit") or {}
        sections.append(
            "\n"
            + _render(
                AgentRole.TESTER,
                "product_qa",
                pass_num=context.get("enrichment_pass") or "?",
                upstream=upstream or "not running",
                health_path=health_path,
                audit_health_ok=audit.get("health_ok"),
                audit_has_html_ui=audit.get("has_html_ui"),
            )
        )
    else:
        sections.append(
            "\n"
            + _render(
                AgentRole.TESTER,
                "probe",
                upstream=upstream or "not running",
                health_path=health_path,
            )
        )
    return "\n".join(sections).strip()


def _build_tester_full_prompt(context: dict) -> str:
    name = context.get("name", "app")
    description = context.get("description", "")
    upstream = context.get("preview_upstream") or context.get("preview_url") or ""
    health_path = context.get("preview_health_path") or "/health"
    stage = context.get("test_stage")
    sections = _header(AgentRole.TESTER, name)
    append_agent_rules_sections(sections, context, compact=True)
    if description:
        sections.append(f"\n## Product\n{description[:500]}")
    contract_block = _contract_section(context, mode="compact")
    if contract_block:
        sections.append(contract_block)
    sections.append(
        f"\n## Preview\n{upstream or 'not running'} | health: GET {health_path}"
    )
    if stage == "write_acceptance":
        sections.append("\n" + _render(AgentRole.TESTER, "write_acceptance"))
    elif stage == "user_perspective_review":
        audit = context.get("preview_audit") or {}
        sections.append(
            "\n"
            + _render(
                AgentRole.TESTER,
                "user_perspective_review",
                cycle_label=context.get("cycle_label") or "this cycle",
                upstream=upstream or "not running",
                health_path=health_path,
                audit_health_ok=audit.get("health_ok"),
                audit_has_html_ui=audit.get("has_html_ui"),
            )
        )
    return "\n".join(sections).strip()


def _build_reviewer_prompt(context: dict) -> str:
    name = context.get("name", "app")
    sections = _header(AgentRole.REVIEWER, name, compact=True)
    append_agent_rules_sections(sections, context, compact=True)
    contract_block = _contract_section(context, mode="summary")
    if contract_block:
        sections.append(contract_block)
    acceptance_report = context.get("acceptance_report")
    if acceptance_report:
        verified = acceptance_report.get("verified", 0)
        total = acceptance_report.get("total", 0)
        sections.append(
            f"\n## Acceptance\n{verified}/{total} verified — "
            + ", ".join(
                f"{rid}={entry.get('status')}"
                for rid, entry in (acceptance_report.get("requirements") or {}).items()
            )
        )
    sections.append(
        "\n"
        + _render(
            AgentRole.REVIEWER,
            "review",
            tests_passed=context.get("tests_passed", False),
            enrichment_passes=context.get("enrichment_passes_completed", 0),
        )
    )
    return "\n".join(sections).strip()


def _build_adversary_prompt(context: dict) -> str:
    name = context.get("name", "app")
    upstream = context.get("preview_upstream") or context.get("preview_url") or ""
    health_path = context.get("preview_health_path") or "/health"
    sections = _header(AgentRole.ADVERSARY, name, compact=True)
    contract_block = _contract_section(context, mode="compact")
    if contract_block:
        sections.append(contract_block)
    sections.append(
        "\n"
        + _render(
            AgentRole.ADVERSARY,
            "adversary",
            upstream=upstream or "not running",
            health_path=health_path,
        )
    )
    return "\n".join(sections).strip()


def build_role_prompt(role: AgentRole, context: dict) -> str:
    if role == AgentRole.ARCHITECT and context.get("repo_exploration"):
        return context.get("repo_exploration_prompt") or (
            "Explore the linked repository and return repo exploration JSON."
        )

    profile = _resolve_profile(role, context)
    builders = {
        PROFILE_DEVELOPER_FIX: _build_developer_fix_prompt,
        PROFILE_DEVELOPER_FEATURE: _build_developer_feature_prompt,
        PROFILE_DEVELOPER_FULL: _build_developer_full_prompt,
        PROFILE_ARCHITECT_ENRICHMENT: _build_architect_enrichment_prompt,
        PROFILE_ARCHITECT_PLANNING: _build_architect_planning_prompt,
        PROFILE_TESTER_LIGHT: _build_tester_light_prompt,
        PROFILE_TESTER_FULL: _build_tester_full_prompt,
        PROFILE_REVIEWER: _build_reviewer_prompt,
        PROFILE_ADVERSARY: _build_adversary_prompt,
    }
    builder = builders.get(profile)
    if builder:
        return builder(context)

    # Fallback — should not happen for known roles
    return _build_developer_full_prompt(context)
