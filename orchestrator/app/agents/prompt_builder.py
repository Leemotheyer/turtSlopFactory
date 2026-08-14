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
You must NOT run `docker`, `docker compose`, `docker run`, `uvicorn`, or any other server to demo or test the app. That wastes time; the factory already owns the running container.

- Public demo URL: {preview_url or "(the factory will publish this after it starts the container)"}
- Preview status: {preview_status}
- The app MUST listen on `0.0.0.0:{preview_port}`
- The app MUST expose `GET {health_path}` returning HTTP 200 JSON `{{"status": "ok"}}`
- Serve the UI so it works behind the gateway path (use relative `fetch('api/...')` URLs, not `/api/...`)
- After you finish, the factory refreshes the preview. Testers probe that container, not a process you start.
"""
    )

    if role == AgentRole.ARCHITECT:
        sections.append(
            """
## Your task
Create project requirements and architecture documentation.

Write two markdown files in the workspace:
1. `requirements.md` — functional/non-functional requirements, exclusions, overview
2. `architecture.md` — stack, API design, testing strategy

Use Python 3.12 + FastAPI, Docker on port 8080, pytest coverage, and a `/health` endpoint.
Do not document a manual docker-compose demo workflow — the factory live preview is how the app is run during development.
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
Do not start a server or container; the factory live preview already runs the app.
"""
            )
        elif stream == "frontend":
            sections.append(
                """
## Your task
Implement or update the **frontend UI**: static HTML/JS served by FastAPI under `app/static/`.
Provide a usable browser interface for the API.
Use relative fetch URLs (`api/items`, not `/api/items`) so the UI works through the factory preview gateway.
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
The factory starts the live preview for you — implement the app, do not try to run Docker.
"""
            )
        if context.get("incremental") and context.get("last_failure"):
            sections.append(f"\n## Fix previous failure\n{context['last_failure'][:4000]}")
    elif role == AgentRole.TESTER:
        upstream = context.get("preview_upstream") or context.get("preview_url") or ""
        sections.append(
            f"""
## Your task
Probe the factory live preview. Do not start Docker or uvicorn.

Live preview: {upstream or "not running"}
Health: GET {health_path}

Report whether the running preview meets the acceptance contract. If it is down, say so —
do not try to start a replacement container.
"""
        )
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
