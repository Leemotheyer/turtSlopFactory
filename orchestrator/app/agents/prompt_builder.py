"""Build Cursor agent prompts from factory pipeline context."""

from __future__ import annotations

from app.models import AgentRole
from app.services.product_enrichment import enrichment_pass_theme_hint


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

    if role == AgentRole.ARCHITECT and context.get("last_failure"):
        sections.append(f"\n## Previous attempt failed\n{str(context['last_failure'])[:4000]}")

    enrichment_pass = context.get("enrichment_pass")
    if enrichment_pass:
        audit = context.get("preview_audit") or {}
        max_features = context.get("max_features_per_pass", 8)
        theme_hint = enrichment_pass_theme_hint(int(enrichment_pass))
        sections.append(
            f"""
## Autonomous enrichment pass {enrichment_pass}/{context.get('max_enrichment_passes', 4)}
The app has a **working live preview**. Each pass must deliver **substantial, user-visible progress** — not tiny tweaks.
Think in terms of complete flows, screens, or capabilities a user would notice in the preview.

{theme_hint}

Preview audit:
- Health OK: {audit.get('health_ok', False)}
- HTML UI detected: {audit.get('has_html_ui', False)}
- Issues found: {', '.join(audit.get('issues') or []) or 'none recorded'}

Write `enrichment-plan.json` in the workspace AND include the same JSON in your reply:
```json
{{
  "features": [
    {{
      "id": "slug",
      "title": "Short title",
      "description": "Detailed scope: backend routes, frontend screens, validation, tests, and what the user will see",
      "scope": "in_scope | uncertain | out_of_scope",
      "priority": "high | medium | low"
    }}
  ],
  "quality_issues": ["list of UX or reliability problems observed"],
  "stop_reason": null
}}
```

Rules:
- Propose **{max_features}** or fewer **high-impact** features. Each feature should touch backend + frontend where applicable.
- Every description must list concrete deliverables (routes, UI screens, states, tests) — not vague "improve UX".
- Prefer **fewer, larger features** over many one-line nits (e.g. "full CRUD with forms" not "add a button color").
- Mark `uncertain` when a feature may be out of scope (payments, OAuth, email/SMS, multi-tenant admin, ML, etc.).
- Mark `out_of_scope` when it clearly contradicts supervisor notes or intake exclusions.
- Set `stop_reason` only when the app is genuinely production-ready and no worthwhile improvements remain.
- Do NOT replan from scratch — iterate on the running product.
- You **cannot** reach the private preview URL from Cursor Cloud. Use the audit summary above and existing code/docs only.
- Do **NOT** write requirements.md, architecture.md, or a greenfield project plan. Do **NOT** use plan mode.
- Your entire reply must be the JSON object (optionally wrapped in a ```json fence). No markdown architecture documents.
"""
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
        if context.get("repo_url"):
            sections.append(
                """
## Your task
Create project requirements and architecture documentation for a **complete, polished application** — not a bare-minimum demo.

Plan user journeys, error handling, validation, empty states, and the core features needed for a shippable v1.
Write two markdown files in the workspace AND repeat both documents in your final reply:
1. `requirements.md` — functional/non-functional requirements, user flows, exclusions, quality bar
2. `architecture.md` — stack, API design, UI structure, testing strategy

Start the reply with `# Requirements` then `# Architecture` so the factory can copy them.

Use Python 3.12 + FastAPI, Docker on port 8080, pytest coverage, and a `/health` endpoint.
Do not document a manual docker-compose demo workflow — the factory live preview is how the app is run during development.
"""
            )
        else:
            sections.append(
                """
## Your task
You are a no-repo Cloud Agent. There is no GitHub repository and nothing you write to disk will be synced.
Do not try to commit, push, clone, or create a repo.

Put BOTH documents in your final reply as markdown headings the factory will copy into `requirements.md` and `architecture.md`:

# Requirements
functional/non-functional requirements, user flows, exclusions, quality bar for a complete v1

# Architecture
stack, API design, UI structure, testing strategy

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
Implement or update the **backend API** (FastAPI): routes, models, validation, tests under `tests/`.
Ensure `/health` and core CRUD endpoints work with proper error responses. Match requirements.md if present.
Build production-quality code — not stubs. Do not start a server or container; the factory live preview already runs the app.
"""
            )
        elif stream == "frontend":
            sections.append(
                """
## Your task
Implement or update the **frontend UI**: static HTML/JS served by FastAPI under `app/static/`.
Provide a polished browser interface: loading states, empty states, validation feedback, mobile-friendly layout.
Use relative fetch URLs (`api/items`, not `/api/items`) so the UI works through the factory preview gateway.
"""
            )
        elif stream == "feature":
            feature_id = context.get("feature_id") or "feature"
            content = context.get("feature_content") or context.get("work_description", "")
            enrichment_cmd = context.get("enrichment_command")
            enrichment_block = ""
            if enrichment_cmd:
                enrichment_block = """
## Enrichment implementation standards
This is an **enrichment pass** — implement **all** listed improvements in this task, not a subset.
- Touch both backend and frontend when the feature needs it.
- Add or update pytest tests for new/changed API behavior.
- Wire the UI with loading, error, and empty states — verify through the factory live preview.
- Do **not** stop after cosmetic-only changes; each item should be a visible capability or flow.
"""
            sections.append(
                f"""
## Your task
Implement feature **{feature_id}**:
{content}
{enrichment_block}
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
        stage = context.get("test_stage", "unit")
        if stage == "product_qa":
            audit = context.get("preview_audit") or {}
            pass_num = context.get("enrichment_pass")
            sections.append(
                f"""
## Your task — product QA on the live preview (enrichment pass {pass_num or "?"})
Interact with the factory live preview like a user. Do not start Docker or uvicorn.

Live preview: {upstream or "not running"}
Health: GET {health_path}
Audit summary: health_ok={audit.get('health_ok')}, has_ui={audit.get('has_html_ui')}

Probe key endpoints and the HTML UI. Write `product-qa.json` with:
- `passed`: boolean — did this enrichment pass add **meaningful** user-visible value?
- `issues`: list of concrete UX/functionality problems still present
- `suggested_features`: list of substantial improvements worth implementing next (not nits)

**Fail the pass** if the only changes were cosmetic (colors, spacing tweaks) while core flows,
forms, lists, or error handling are still missing. Enrichment should feel like real product progress.
Reject bare-minimum demos missing empty states, validation, or core flows.
"""
            )
        else:
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
Enrichment passes completed: {context.get('enrichment_passes_completed', 0)}.

The app should feel **complete and polished**, not a bare scaffold. Reject if core UX polish is missing
unless enrichment passes were exhausted and remaining gaps are documented.

Write `review.json` with:
- decision: "approve" or "reject"
- checklist: requirements_documented, architecture_documented, all_tests_passed,
  dockerfile_present, supervisor_notes_applied (booleans)
- concerns: list of strings
- severity: "low" or "high"
"""
        )

    return "\n".join(sections).strip()
