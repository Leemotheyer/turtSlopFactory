"""Discovery agent: turns a broad idea into a loose plan and intake form."""

from app.models import IntakeField, IntakeFieldType


def _detect_app_type(description: str) -> str:
    desc = description.lower()
    if any(w in desc for w in ("api", "rest", "graphql", "endpoint")):
        if any(w in desc for w in ("ui", "web", "browser", "dashboard", "frontend")):
            return "fullstack_web"
        return "api_service"
    if any(w in desc for w in ("worker", "cron", "queue", "background", "poll")):
        return "background_worker"
    if any(w in desc for w in ("cli", "command line", "terminal")):
        return "cli_tool"
    return "fullstack_web"


def generate_discovery(name: str, description: str) -> tuple[str, list[IntakeField]]:
    """Return (loose_plan_markdown, form_fields)."""
    app_type = _detect_app_type(description)
    desc_lower = description.lower()

    type_labels = {
        "fullstack_web": "Full-stack web application (API + browser UI)",
        "api_service": "API service (no browser UI)",
        "background_worker": "Background worker / scheduled job",
        "cli_tool": "CLI tool",
    }

    loose_plan = f"""# Discovery plan: {name}

## Your idea
{description}

## Initial interpretation
This looks like a **{type_labels.get(app_type, app_type)}**. The factory will scaffold a Docker-deployable app based on your answers to the intake form below.

## Proposed approach (loose)
1. **Scope** — Lock in must-haves and explicit exclusions from your form answers
2. **Architecture** — Document requirements, API surface, and deployment model
3. **Implementation** — Generate code, tests, and Docker configuration
4. **Validation** — Unit, integration, and smoke tests against staging
5. **Review** — Acceptance checklist before production promotion

## Open questions
The intake form below captures specifics we need before building. Answer what you can — required fields help us avoid building the wrong thing.

## Assumptions (until you say otherwise)
- Self-hosted Docker deployment
- Python + FastAPI backend unless you specify otherwise
- MVP scope: ship working core features first, defer nice-to-haves
"""

    fields: list[IntakeField] = [
        IntakeField(
            id="primary_goal",
            label="What should this app achieve?",
            type=IntakeFieldType.TEXTAREA,
            help="One or two sentences on the core outcome users get.",
            placeholder="e.g. Let users track invoices and export them as PDF",
            required=True,
        ),
        IntakeField(
            id="target_users",
            label="Who will use it?",
            type=IntakeFieldType.TEXT,
            help="Be specific: just you, a team, public internet users, etc.",
            placeholder="e.g. Small business owners, internal ops team",
            required=True,
        ),
        IntakeField(
            id="must_have_features",
            label="Must-have features (MVP)",
            type=IntakeFieldType.TEXTAREA,
            help="List the features required for v1. One per line is fine.",
            placeholder="e.g.\n- User login\n- Create and list items\n- Export to CSV",
            required=True,
        ),
        IntakeField(
            id="out_of_scope",
            label="Explicitly out of scope",
            type=IntakeFieldType.TEXTAREA,
            help="Things we should NOT build in v1. Critical for avoiding scope creep.",
            placeholder="e.g.\n- No payment processing\n- No mobile app\n- No multi-tenant",
            required=False,
            default="",
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
            default=type_labels.get(app_type, "Web browser UI + REST API"),
            required=True,
        ),
        IntakeField(
            id="authentication",
            label="Authentication needed?",
            type=IntakeFieldType.SELECT,
            options=[
                "No auth (single-user / internal tool)",
                "Simple login (username/password)",
                "OAuth / SSO (Google, GitHub, etc.)",
                "API keys only",
            ],
            default="No auth (single-user / internal tool)"
            if "auth" not in desc_lower
            else "Simple login (username/password)",
            required=True,
        ),
        IntakeField(
            id="data_persistence",
            label="Data storage",
            type=IntakeFieldType.SELECT,
            options=[
                "In-memory (demo / ephemeral)",
                "SQLite file",
                "PostgreSQL",
                "External service (I'll configure later)",
            ],
            default="In-memory (demo / ephemeral)",
            required=True,
        ),
    ]

    # Dynamic follow-up questions based on idea keywords
    if any(w in desc_lower for w in ("rss", "feed", "poll", "scrape", "crawl")):
        fields.append(
            IntakeField(
                id="poll_interval",
                label="How often should it poll/fetch?",
                type=IntakeFieldType.SELECT,
                options=["Every 5 minutes", "Every 15 minutes", "Hourly", "Daily", "On demand only"],
                default="Every 15 minutes",
                required=True,
            )
        )

    if any(w in desc_lower for w in ("invoice", "billing", "payment", "subscription")):
        fields.append(
            IntakeField(
                id="payments",
                label="Payment processing in v1?",
                type=IntakeFieldType.SELECT,
                options=["No payments in v1", "Stripe integration", "Manual/offline only"],
                default="No payments in v1",
                required=True,
            )
        )

    if any(w in desc_lower for w in ("chat", "message", "notification", "email", "slack")):
        fields.append(
            IntakeField(
                id="notifications",
                label="Notification channels needed?",
                type=IntakeFieldType.MULTISELECT,
                options=["Email", "In-app only", "Webhook", "Slack", "None"],
                default="In-app only",
                required=False,
            )
        )

    if any(w in desc_lower for w in ("multi", "team", "organization", "tenant")):
        fields.append(
            IntakeField(
                id="multi_tenancy",
                label="Multi-user / multi-tenant?",
                type=IntakeFieldType.SELECT,
                options=[
                    "Single user only",
                    "Multiple users, shared data",
                    "Multi-tenant (isolated per org)",
                ],
                default="Single user only",
                required=True,
            )
        )

    fields.append(
        IntakeField(
            id="success_criteria",
            label="How will you know v1 is done?",
            type=IntakeFieldType.TEXTAREA,
            help="Acceptance criteria — what must work before you call it shippable?",
            placeholder="e.g. I can deploy with docker compose, open the UI, create an item, and see it after refresh",
            required=True,
        )
    )

    fields.append(
        IntakeField(
            id="anything_else",
            label="Anything else we should know?",
            type=IntakeFieldType.TEXTAREA,
            help="Constraints, preferences, integrations, or references.",
            required=False,
            default="",
        )
    )

    return loose_plan, fields
