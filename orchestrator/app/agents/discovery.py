"""Discovery: turns a broad idea into a loose plan and bespoke intake form."""

from typing import Any

from app.models import IntakeField, IntakeFieldType, NoteType
from app.services.intake_analysis import (
    DescriptionAnalysis,
    analyze_project_description,
    bespoke_to_intake_field,
)

APP_TYPE_LABELS = {
    "fullstack_web": "Full-stack web application (API + browser UI)",
    "api_service": "API service (no browser UI)",
    "background_worker": "Background worker / scheduled job",
    "cli_tool": "CLI tool",
}

APP_SURFACE_OPTIONS = {
    "fullstack_web": "Web browser UI + REST API",
    "api_service": "REST API only (no UI)",
    "background_worker": "Background worker (no UI)",
    "cli_tool": "CLI tool",
}

AUTH_OPTIONS = [
    "No auth (single-user / internal tool)",
    "Simple login (username/password)",
    "OAuth / SSO (Google, GitHub, etc.)",
    "API keys only",
]

AUTH_DEFAULTS = {
    "none": "No auth (single-user / internal tool)",
    "simple": "Simple login (username/password)",
    "oauth": "OAuth / SSO (Google, GitHub, etc.)",
    "api_key": "API keys only",
    "unclear": "No auth (single-user / internal tool)",
}

PERSISTENCE_OPTIONS = [
    "In-memory (demo / ephemeral)",
    "SQLite file",
    "PostgreSQL",
    "External service (I'll configure later)",
]

PERSISTENCE_DEFAULTS = {
    "memory": "In-memory (demo / ephemeral)",
    "sqlite": "SQLite file",
    "postgres": "PostgreSQL",
    "external": "External service (I'll configure later)",
    "unclear": "In-memory (demo / ephemeral)",
}


def _build_loose_plan(
    name: str,
    description: str,
    analysis: DescriptionAnalysis,
    *,
    repo_context: dict[str, Any] | None = None,
) -> str:
    repo_context = repo_context or {}
    has_existing = bool(repo_context.get("has_existing_app"))
    app_label = APP_TYPE_LABELS.get(analysis.app_type, analysis.app_type)

    repo_section = ""
    if has_existing:
        stack = ", ".join(repo_context.get("stack") or []) or "see repository"
        repo_section = f"""
## Existing repository detected
The factory cloned **{repo_context.get('repo_name', 'your linked repo')}** and found an existing codebase.

- Stack: {stack}
- Backend: {'yes' if repo_context.get('has_backend') else 'no'}
- UI: {'yes' if repo_context.get('has_frontend') else 'no'}
- Tests: {'yes' if repo_context.get('has_tests') else 'no'}

**Approach:** extend what exists — fill gaps from your description and intake answers rather than rebuilding from scratch.
"""

    themes_line = ""
    if analysis.themes:
        themes_line = "\n**Themes detected:** " + ", ".join(t.replace("_", " ") for t in analysis.themes)

    features_section = ""
    if analysis.mentioned_features:
        features_section = "\n## Features we picked up from your description\n" + "\n".join(
            f"- {f}" for f in analysis.mentioned_features
        )

    open_section = ""
    if analysis.open_questions:
        open_section = "\n## What we still need from you\n" + "\n".join(
            f"- {q}" for q in analysis.open_questions
        )

    bespoke_section = ""
    if analysis.bespoke_questions:
        bespoke_section = (
            f"\n## Tailored follow-ups ({len(analysis.bespoke_questions)})\n"
            "The intake form includes domain-specific questions based on your description — "
            "not a generic template."
        )

    return f"""# Discovery plan: {name}

## Your idea
{description.strip()}
{repo_section}
## Our interpretation
{analysis.interpretation}
{themes_line}

This looks like a **{app_label}**. The factory will {"extend your linked repository" if has_existing else "scaffold a Docker-deployable app"} based on your intake answers.
{features_section}
{open_section}
{bespoke_section}

## Proposed approach (loose)
1. **Scope** — Lock must-haves and exclusions from your tailored intake form
2. **Architecture** — Document requirements, API surface, and deployment model{" (building on existing code)" if has_existing else ""}
3. **Implementation** — {"Extend the codebase" if has_existing else "Generate code"}, tests, and Docker configuration
4. **Validation** — Unit, integration, and smoke tests against staging
5. **Review** — Acceptance checklist before production promotion

## Assumptions (until you say otherwise)
- Self-hosted Docker deployment
- {"Match the existing project stack where possible" if has_existing else "Python + FastAPI backend unless you specify otherwise"}
- MVP scope: ship working core features first, defer nice-to-haves
"""


def _core_fields(
    analysis: DescriptionAnalysis,
    suggested_responses: dict[str, str | list[str]],
    *,
    has_existing: bool,
) -> list[IntakeField]:
    fields: list[IntakeField] = []

    if has_existing:
        fields.extend(
            [
                IntakeField(
                    id="existing_code_approach",
                    label="How should the factory treat the existing code?",
                    type=IntakeFieldType.SELECT,
                    options=[
                        "Extend existing code (recommended)",
                        "Refactor in place — improve structure but keep behavior",
                        "Replace only specific modules (describe in notes)",
                        "Full rewrite (only if necessary)",
                    ],
                    default=suggested_responses.get(
                        "existing_code_approach", "Extend existing code (recommended)"
                    ),
                    required=True,
                    category="existing",
                    note_type=NoteType.INSTRUCTION,
                ),
                IntakeField(
                    id="gaps_to_address",
                    label="What should the factory add or improve?",
                    type=IntakeFieldType.TEXTAREA,
                    help="Focus on missing features, bugs, or polish — not re-implementing what already works.",
                    placeholder="e.g.\n- Add settings page for API URL\n- Fix mobile layout\n- Add export to CSV",
                    default=suggested_responses.get("gaps_to_address")
                    or "Fill gaps from my project description — do not rebuild working features.",
                    required=True,
                    category="existing",
                    note_type=NoteType.FEATURE,
                    prefill_source="readme" if suggested_responses.get("gaps_to_address") else None,
                ),
            ]
        )

    # Vision confirmation — bespoke to this project
    fields.append(
        IntakeField(
            id="confirm_interpretation",
            label="Does this match what you want to build?",
            type=IntakeFieldType.TEXTAREA,
            help="We summarized your idea below. Edit anything that's wrong or add missing context.",
            default=analysis.interpretation,
            required=True,
            category="vision",
            note_type=NoteType.INSTRUCTION,
            prefill_source="inferred",
        )
    )

    fields.extend(
        [
            IntakeField(
                id="primary_goal",
                label="What should this app achieve?",
                type=IntakeFieldType.TEXTAREA,
                help="One or two sentences on the core outcome users get.",
                placeholder="e.g. Let users track invoices and export them as PDF",
                required=True,
                category="vision",
                default=suggested_responses.get("primary_goal") or None,
                prefill_source="description" if suggested_responses.get("primary_goal") else None,
            ),
            IntakeField(
                id="target_users",
                label="Who will use it?",
                type=IntakeFieldType.TEXT,
                help="Be specific: just you, a team, public internet users, etc.",
                placeholder="e.g. Small business owners, internal ops team",
                required=True,
                category="users",
                default=analysis.user_hint or suggested_responses.get("target_users"),
                prefill_source="description" if analysis.user_hint else None,
            ),
            IntakeField(
                id="must_have_features",
                label="Must-have features (MVP)",
                type=IntakeFieldType.TEXTAREA,
                help="List features required for v1. We pre-filled any we found in your description — add or remove.",
                placeholder="e.g.\n- User login\n- Create and list items\n- Export to CSV",
                required=True,
                category="features",
                default=suggested_responses.get("must_have_features")
                or (
                    "\n".join(f"- {f}" for f in analysis.mentioned_features)
                    if analysis.mentioned_features
                    else None
                ),
                prefill_source=(
                    "description"
                    if analysis.mentioned_features or suggested_responses.get("must_have_features")
                    else None
                ),
                note_type=NoteType.FEATURE,
            ),
            IntakeField(
                id="out_of_scope",
                label="Explicitly out of scope",
                type=IntakeFieldType.TEXTAREA,
                help="Things we should NOT build in v1. Critical for avoiding scope creep.",
                placeholder="e.g.\n- No payment processing\n- No mobile app\n- No multi-tenant",
                required=False,
                category="features",
                default=suggested_responses.get("out_of_scope")
                or (
                    "\n".join(f"- {s}" for s in analysis.suggested_out_of_scope)
                    if analysis.suggested_out_of_scope
                    else ""
                ),
                prefill_source="inferred" if analysis.suggested_out_of_scope else None,
                note_type=NoteType.SCOPE_OUT,
            ),
            IntakeField(
                id="app_surface",
                label="How should users interact with it?",
                type=IntakeFieldType.SELECT,
                options=[
                    "Web browser UI + REST API",
                    "REST API only (no UI)",
                    "Background worker (no UI)",
                    "CLI tool",
                ],
                default=suggested_responses.get("app_surface")
                or APP_SURFACE_OPTIONS.get(analysis.app_type, "Web browser UI + REST API"),
                required=True,
                category="technical",
            ),
            IntakeField(
                id="authentication",
                label="Authentication needed?",
                type=IntakeFieldType.SELECT,
                options=AUTH_OPTIONS,
                default=suggested_responses.get("authentication")
                or AUTH_DEFAULTS.get(analysis.auth_signal, AUTH_DEFAULTS["unclear"]),
                required=True,
                category="users",
            ),
            IntakeField(
                id="data_persistence",
                label="Data storage",
                type=IntakeFieldType.SELECT,
                options=PERSISTENCE_OPTIONS,
                default=suggested_responses.get("data_persistence")
                or PERSISTENCE_DEFAULTS.get(
                    analysis.persistence_signal, PERSISTENCE_DEFAULTS["unclear"]
                ),
                required=True,
                category="technical",
            ),
            IntakeField(
                id="success_criteria",
                label="How will you know v1 is done?",
                type=IntakeFieldType.TEXTAREA,
                help="Acceptance criteria — what must work before you call it shippable?",
                placeholder="e.g. I can deploy with docker compose, open the UI, create an item, and see it after refresh",
                required=True,
                category="wrapup",
                note_type=NoteType.INSTRUCTION,
            ),
            IntakeField(
                id="anything_else",
                label="Anything else we should know?",
                type=IntakeFieldType.TEXTAREA,
                help="Constraints, preferences, integrations, or references.",
                required=False,
                category="wrapup",
                default=suggested_responses.get("anything_else") or "",
                note_type=NoteType.GENERAL,
            ),
        ]
    )

    return fields


def generate_discovery(
    name: str,
    description: str,
    *,
    repo_context: dict[str, Any] | None = None,
    suggested_responses: dict[str, str | list[str]] | None = None,
) -> tuple[str, list[IntakeField]]:
    """Return (loose_plan_markdown, form_fields) tailored to the project description."""
    repo_context = repo_context or {}
    suggested_responses = suggested_responses or {}

    analysis = analyze_project_description(name, description, repo_context=repo_context)
    loose_plan = _build_loose_plan(name, description, analysis, repo_context=repo_context)

    fields = _core_fields(
        analysis,
        suggested_responses,
        has_existing=bool(repo_context.get("has_existing_app")),
    )

    # Add bespoke domain / ambiguity questions (skip ids already in core set)
    core_ids = {f.id for f in fields}
    for bespoke in analysis.bespoke_questions:
        if bespoke.id not in core_ids:
            fields.append(bespoke_to_intake_field(bespoke))

    return loose_plan, fields
