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
from app.models import AgentRole
from app.services.agent_rules import append_agent_rules_sections
from app.services.memory import format_memory_for_prompt
from app.services.product_enrichment import enrichment_pass_theme_hint
from app.services.repo_analysis import format_repo_analysis_for_prompt

PROMPTS_DIR = Path(__file__).parent / "prompts"


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


def _contract_section(context: dict) -> str:
    contract = context.get("contract")
    if not contract:
        return ""
    lines = ["\n## Project contract (the definition of done)"]
    goal = getattr(contract, "goal", "") or ""
    if goal:
        lines.append(f"Goal: {goal[:500]}")
    for req in getattr(contract, "requirements", [])[:12]:
        lines.append(f"- **{req.id}** ({req.priority}): {req.description}")
        for criterion in req.acceptance[:4]:
            lines.append(f"  - accept: {criterion}")
    non_goals = getattr(contract, "non_goals", None) or []
    if non_goals:
        lines.append("Non-goals: " + "; ".join(str(n) for n in non_goals[:6]))
    lines.append(
        "Verification: name pytest tests `test_<req_id_lowercase>_*` so the factory "
        "records them as evidence for the matching requirement."
    )
    return "\n".join(lines)


def build_role_prompt(role: AgentRole, context: dict) -> str:
    if role == AgentRole.ARCHITECT and context.get("repo_exploration"):
        return context.get("repo_exploration_prompt") or "Explore the linked repository and return repo exploration JSON."

    name = context.get("name", "app")
    description = context.get("description", "")
    original = context.get("original_description") or description
    notes = context.get("notes", [])
    intake = context.get("intake", {})
    input_responses = context.get("input_responses", [])

    sections: list[str] = [
        f"You are the **{role.value}** agent for the turtSlopFactory software pipeline.",
        f"Project: **{name}**",
        rules_for_role(role),
    ]
    append_agent_rules_sections(sections, context)
    sections.append(f"\n## Product vision (original request)\n{original.strip()}")

    if description.strip() and description.strip() != original.strip():
        sections.append(f"\n## Refined specification (after intake)\n{description.strip()}")

    contract_block = _contract_section(context)
    if contract_block:
        sections.append(contract_block)

    repo_block = format_repo_analysis_for_prompt(context.get("repo_analysis"))
    if repo_block:
        sections.append(f"\n{repo_block}")

    memory_block = format_memory_for_prompt(context.get("project_memory"))
    if memory_block:
        sections.append(memory_block)

    git_history = context.get("git_history")
    if git_history and context.get("repo_url"):
        sections.append(
            "\n## Recent git history (the why behind the code)\n```\n"
            + str(git_history)[:1200]
            + "\n```"
        )

    if notes:
        sections.append("\n## Supervisor notes (must follow)")
        for note in notes:
            label = note.get("type", "note").replace("_", " ").title()
            sections.append(f"- [{label}] {note.get('content', '')}")

    if intake:
        sections.append("\n## Intake form answers")
        for key, val in intake.items():
            if isinstance(val, list):
                val = ", ".join(val)
            sections.append(f"- {key.replace('_', ' ').title()}: {val}")

    if context.get("loose_plan"):
        sections.append("\n## Discovery plan\nSee discovery-plan.md in artifacts.")

    if input_responses:
        sections.append("\n## Supervisor decisions (apply these)")
        for resp in input_responses:
            decision = resp.get("resolved_decision") or resp.get("default_decision", "")
            sections.append(f"- Q: {resp.get('question', '')}")
            sections.append(f"  A: {decision}")

    if context.get("isolate_branch") and context.get("work_branch"):
        base = context.get("base_branch", "main")
        work = context["work_branch"]
        sections.append(
            f"""
## Git workflow (isolated branch)
- **Production branch:** `{base}` — do NOT commit or push here.
- **Your working branch:** `{work}` — all commits and pushes go here only.
- The factory will ask before merging into `{base}`.
"""
        )

    preview_url = context.get("preview_url") or ""
    preview_status = context.get("preview_status") or "not started"
    health_path = context.get("preview_health_path") or "/health"
    preview_port = context.get("preview_app_port") or 8080
    sections.append(
        f"""
## Live preview (factory-managed — do not start it yourself)
The factory automatically deploys and refreshes a live preview container for users and pipeline testers.
You must NOT run `docker`, `docker compose`, `docker run`, `uvicorn`, or any other server to demo or test the app.

- Public demo URL: {preview_url or "(the factory will publish this after it starts the container)"}
- Preview status: {preview_status}
- The app MUST listen on `0.0.0.0:{preview_port}`
- The app MUST expose `GET {health_path}` returning HTTP 200 JSON `{{"status": "ok"}}`
- Serve the UI so it works behind the gateway path (use relative `fetch('api/...')` URLs, not `/api/...`)
- After you finish, the factory refreshes the preview. Testers probe that container, not a process you start.
"""
    )

    if role == AgentRole.ARCHITECT and context.get("last_failure"):
        sections.append(f"\n## Previous attempt failed\n{str(context['last_failure'])[:4000]}")

    enrichment_pass = context.get("enrichment_pass")
    if enrichment_pass:
        audit = context.get("preview_audit") or {}
        max_features = context.get("max_features_per_pass", 8)
        theme_hint = enrichment_pass_theme_hint(int(enrichment_pass))
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
                audit_issues=", ".join(audit.get("issues") or []) or "none recorded",
                max_features=max_features,
            )
        )
        from app.services.intake_contract import intake_capability_lines

        intake_lines = intake_capability_lines(intake)
        if intake_lines:
            sections.append(
                "\n## Intake capabilities (always in scope — implement, do not question)\n"
                + "\n".join(f"- {line}" for line in intake_lines[:20])
            )
        ux_backlog = context.get("ux_improvement_backlog") or []
        if ux_backlog:
            sections.append(
                "\n## UX improvements from user-journey testing (polish — not blocking)\n"
                + "\n".join(
                    f"- {item.get('title', 'Improvement')}: {str(item.get('description', ''))[:160]}"
                    for item in ux_backlog[:12]
                    if isinstance(item, dict)
                )
            )
        if role == AgentRole.ARCHITECT:
            sections.append(
                """
## Your task
Propose the next batch of **substantial** in-scope improvements as `enrichment-plan.json`.
Each feature should be enough work to meaningfully change what a user sees or can do in the preview.
Base decisions on the preview audit, requirements.md, and the current codebase — not a from-scratch redesign.
"""
            )

    elif role == AgentRole.ARCHITECT:
        draft = context.get("requirements_draft")
        if draft:
            sections.append(
                f"""
## Requirements draft (factory-generated — refine, do not ignore)
The factory prepared this draft from intake and repo analysis. **Update and complete it** rather than starting from scratch:

{draft[:6000]}
"""
            )
        if context.get("repo_url"):
            sections.append("\n" + _render(AgentRole.ARCHITECT, "plan_repo"))
        else:
            sections.append("\n" + _render(AgentRole.ARCHITECT, "plan_no_repo"))
    elif role == AgentRole.DEVELOPER:
        stream = context.get("work_stream")
        existing_note = ""
        if context.get("repo_analysis", {}).get("has_existing_app"):
            existing_note = """
## Existing codebase
Extend the current implementation. **Do not rebuild** working routes, models, or UI unless this task explicitly says to replace them.
"""
        if stream == "backend":
            sections.append("\n" + _render(AgentRole.DEVELOPER, "backend", existing_note=existing_note))
        elif stream == "frontend":
            sections.append("\n" + _render(AgentRole.DEVELOPER, "frontend", existing_note=existing_note))
        elif stream == "feature":
            feature_id = context.get("feature_id") or "feature"
            content = context.get("feature_content") or context.get("work_description", "")
            enrichment_cmd = context.get("enrichment_command")
            enrichment_block = ""
            if enrichment_cmd:
                enrichment_block = _render(AgentRole.DEVELOPER, "enrichment_block")
            sections.append(
                "\n"
                + _render(
                    AgentRole.DEVELOPER,
                    "feature",
                    feature_id=feature_id,
                    content=content,
                    existing_note=existing_note,
                    enrichment_block=enrichment_block,
                )
            )
        else:
            sections.append("\n" + _render(AgentRole.DEVELOPER, "full", existing_note=existing_note))
        if context.get("incremental") and context.get("last_failure"):
            sections.append(f"\n## Fix previous failure\n{context['last_failure'][:4000]}")
            regression_hint = context.get("regression_test_hint")
            if regression_hint:
                sections.append(
                    f"\nAfter fixing, add a regression test `tests/regression/{regression_hint}` "
                    "that fails on the old behavior and passes on the fix. Do not modify existing tests."
                )
    elif role == AgentRole.TESTER:
        upstream = context.get("preview_upstream") or context.get("preview_url") or ""
        stage = context.get("test_stage", "unit")
        if stage == "write_acceptance":
            sections.append("\n" + _render(AgentRole.TESTER, "write_acceptance"))
        elif stage == "product_qa":
            audit = context.get("preview_audit") or {}
            pass_num = context.get("enrichment_pass")
            sections.append(
                "\n"
                + _render(
                    AgentRole.TESTER,
                    "product_qa",
                    pass_num=pass_num or "?",
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
    elif role == AgentRole.ADVERSARY:
        upstream = context.get("preview_upstream") or context.get("preview_url") or ""
        sections.append(
            "\n"
            + _render(
                AgentRole.ADVERSARY,
                "adversary",
                upstream=upstream or "not running",
                health_path=health_path,
            )
        )
    elif role == AgentRole.REVIEWER:
        tests_passed = context.get("tests_passed", False)
        sections.append(
            "\n"
            + _render(
                AgentRole.REVIEWER,
                "review",
                tests_passed=tests_passed,
                enrichment_passes=context.get("enrichment_passes_completed", 0),
            )
        )
        acceptance_report = context.get("acceptance_report")
        if acceptance_report:
            verified = acceptance_report.get("verified", 0)
            total = acceptance_report.get("total", 0)
            sections.append(
                f"\n## Acceptance report (factory-evaluated)\n"
                f"{verified}/{total} requirement(s) verified with evidence. "
                "Statuses: "
                + ", ".join(
                    f"{rid}={entry.get('status')}"
                    for rid, entry in (acceptance_report.get("requirements") or {}).items()
                )
            )

    return "\n".join(sections).strip()
