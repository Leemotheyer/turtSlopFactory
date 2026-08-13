"""Build Cursor agent prompts from factory pipeline context."""

from __future__ import annotations

from app.models import AgentRole


def build_role_prompt(role: AgentRole, context: dict) -> str:
    name = context.get("name", "app")
    description = context.get("description", "")
    notes = context.get("notes", [])
    intake = context.get("intake", {})
    input_responses = context.get("input_responses", [])

    sections: list[str] = [
        f"You are the **{role.value}** agent for the turtSlopFactory software pipeline.",
        f"Project: **{name}**",
        f"\n## Description\n{description}",
    ]

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

    if role == AgentRole.ARCHITECT:
        sections.append(
            """
## Your task
Create project requirements and architecture documentation.

Write two markdown files in the workspace:
1. `requirements.md` — functional/non-functional requirements, exclusions, overview
2. `architecture.md` — stack, API design, testing strategy

Use Python 3.12 + FastAPI, Docker on port 8080, pytest coverage, and a `/health` endpoint.
"""
        )
    elif role == AgentRole.DEVELOPER:
        stream = context.get("work_stream")
        if stream == "backend":
            sections.append(
                """
## Your task
Implement or update the **backend API** (FastAPI): routes, models, tests under `tests/`.
Ensure `/health` and item CRUD endpoints work. Match requirements.md if present.
"""
            )
        elif stream == "frontend":
            sections.append(
                """
## Your task
Implement or update the **frontend UI**: static HTML/JS served by FastAPI under `app/static/`.
Provide a usable browser interface for the API.
"""
            )
        elif stream == "feature":
            feature_id = context.get("feature_id") or "feature"
            content = context.get("feature_content") or context.get("work_description", "")
            sections.append(
                f"""
## Your task
Implement feature **{feature_id}**:
{content}
"""
            )
        else:
            sections.append(
                """
## Your task
Implement the full application: FastAPI backend, static frontend, Dockerfile, docker-compose,
requirements.txt, and pytest tests. Match requirements.md and architecture.md if present.
"""
            )
        if context.get("incremental") and context.get("last_failure"):
            sections.append(f"\n## Fix previous failure\n{context['last_failure'][:4000]}")
    elif role == AgentRole.REVIEWER:
        tests_passed = context.get("tests_passed", False)
        sections.append(
            f"""
## Your task
Review the project for production readiness. Tests passed: {tests_passed}.

Write `review.json` with:
- decision: "approve" or "reject"
- checklist: requirements_documented, architecture_documented, all_tests_passed,
  dockerfile_present, supervisor_notes_applied (booleans)
- concerns: list of strings
- severity: "low" or "high"
"""
        )

    return "\n".join(sections).strip()
