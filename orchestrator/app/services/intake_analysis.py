"""Analyze project descriptions to infer gaps and generate bespoke intake questions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models import IntakeField, IntakeFieldType, NoteType


@dataclass
class BespokeQuestion:
    id: str
    label: str
    type: IntakeFieldType = IntakeFieldType.TEXT
    help: str = ""
    placeholder: str = ""
    options: list[str] = field(default_factory=list)
    required: bool = True
    default: str | None = None
    category: str = "domain"
    note_type: NoteType | None = None
    show_when: dict[str, str | list[str]] | None = None
    prefill_source: str | None = None


@dataclass
class DescriptionAnalysis:
    app_type: str
    domains: list[str]
    themes: list[str]
    mentioned_features: list[str]
    user_hint: str | None
    auth_signal: str  # unclear | none | simple | oauth | api_key
    persistence_signal: str  # unclear | memory | sqlite | postgres | external
    ui_signal: str  # unclear | web | api_only | worker | cli
    reference_apps: list[str]
    open_questions: list[str]
    interpretation: str
    suggested_out_of_scope: list[str]
    bespoke_questions: list[BespokeQuestion] = field(default_factory=list)


def _detect_app_type(description: str) -> str:
    desc = description.lower()
    if any(w in desc for w in ("api", "rest", "graphql", "endpoint", "webhook")):
        if any(w in desc for w in ("ui", "web", "browser", "dashboard", "frontend", "page", "portal")):
            return "fullstack_web"
        return "api_service"
    if any(w in desc for w in ("worker", "cron", "queue", "background", "poll", "scheduler", "job")):
        return "background_worker"
    if any(w in desc for w in ("cli", "command line", "terminal")):
        return "cli_tool"
    return "fullstack_web"


def _detect_domains(desc_lower: str) -> list[str]:
    domain_keywords: dict[str, tuple[str, ...]] = {
        "rss_feeds": ("rss", "feed", "atom", "subscribe", "reader"),
        "scraping": ("scrape", "crawl", "spider", "harvest", "extract data from"),
        "dashboard": ("dashboard", "analytics", "metrics", "chart", "report", "kpi", "visualization"),
        "ecommerce": ("shop", "store", "cart", "checkout", "product catalog", "inventory", "order"),
        "billing": ("invoice", "billing", "payment", "subscription", "stripe", "pricing"),
        "scheduling": ("calendar", "booking", "appointment", "schedule", "reservation", "availability"),
        "messaging": ("chat", "message", "conversation", "inbox", "slack", "email", "notification"),
        "content": ("blog", "cms", "article", "publish", "editor", "markdown", "wiki"),
        "search": ("search", "filter", "index", "full-text", "query"),
        "automation": ("automate", "workflow", "trigger", "pipeline", "orchestrat"),
        "monitoring": ("monitor", "alert", "uptime", "watch", "observability", "health check"),
        "integration": ("integrate", "sync", "komga", "github", "jira", "notion", "webhook", "third-party"),
        "auth_users": ("login", "signup", "user account", "profile", "role", "permission", "team"),
        "files": ("upload", "file", "image", "pdf", "document", "media", "attachment"),
        "crud_data": ("crud", "manage", "track", "list", "create", "edit", "delete", "record", "database"),
    }
    found: list[str] = []
    for domain, keywords in domain_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            found.append(domain)
    return found


def _extract_features_from_description(description: str) -> list[str]:
    features: list[str] = []
    for line in description.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "• ", "1.", "2.", "3.")):
            text = re.sub(r"^[\-*•\d.]+\s*", "", stripped).strip()
            if 3 < len(text) < 200:
                features.append(text)
    # Sentence-level feature hints: "with X", "including X", "that lets users X"
    for match in re.finditer(
        r"(?:with|including|supports?|allows?|enables?|featuring)\s+([^.!?\n]{8,120})",
        description,
        re.IGNORECASE,
    ):
        feat = match.group(1).strip().rstrip(",")
        if feat and feat not in features:
            features.append(feat)
    return features[:10]


def _extract_user_hint(description: str) -> str | None:
    patterns = [
        r"(?:for|used by|targeting|aimed at)\s+([^.!?\n]{5,80})",
        r"(?:users?|customers?|teams?)\s+(?:who|that|are)\s+([^.!?\n]{5,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _detect_auth_signal(desc_lower: str) -> str:
    if any(w in desc_lower for w in ("no auth", "no login", "without auth", "single user", "personal tool")):
        return "none"
    if any(w in desc_lower for w in ("oauth", "google sign", "github sign", "sso", "social login")):
        return "oauth"
    if any(w in desc_lower for w in ("api key", "api token", "bearer token")):
        return "api_key"
    if any(w in desc_lower for w in ("login", "sign in", "signup", "sign up", "password", "authentication", "user account")):
        return "simple"
    return "unclear"


def _detect_persistence_signal(desc_lower: str, repo_context: dict[str, Any] | None) -> str:
    repo_context = repo_context or {}
    if any(w in desc_lower for w in ("postgres", "postgresql", "pg")):
        return "postgres"
    if "sqlite" in desc_lower:
        return "sqlite"
    if any(w in desc_lower for w in ("in-memory", "in memory", "ephemeral", "demo only", "no database")):
        return "memory"
    if any(w in desc_lower for w in ("redis", "mongodb", "mysql", "supabase", "firebase")):
        return "external"
    stack = " ".join(repo_context.get("stack") or []).lower()
    if "postgres" in stack or (repo_context.get("has_dockerfile") and "compose" in desc_lower):
        return "postgres"
    if repo_context.get("has_existing_app"):
        return "unclear"  # ask — likely keep existing
    return "unclear"


def _detect_ui_signal(desc_lower: str, app_type: str) -> str:
    if app_type == "api_service":
        return "api_only"
    if app_type == "background_worker":
        return "worker"
    if app_type == "cli_tool":
        return "cli"
    if any(w in desc_lower for w in ("no ui", "api only", "headless", "backend only")):
        return "api_only"
    if any(w in desc_lower for w in ("mobile", "responsive", "web app", "browser", "dashboard", "ui", "frontend")):
        return "web"
    return "unclear"


def _extract_reference_apps(description: str) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(
        r"(?:like|similar to|inspired by|clone of|style of)\s+([A-Za-z0-9][A-Za-z0-9 .-]{2,40})",
        description,
        re.IGNORECASE,
    ):
        ref = match.group(1).strip().rstrip(".")
        if ref.lower() not in ("this", "that", "it"):
            refs.append(ref)
    return refs[:3]


def _suggest_out_of_scope(domains: list[str], desc_lower: str) -> list[str]:
    suggestions: list[str] = []
    if "billing" not in domains and "payment" not in desc_lower:
        suggestions.append("Payment processing")
    if "messaging" not in domains:
        suggestions.append("Push notifications / email alerts")
    if "auth_users" not in domains and "login" not in desc_lower:
        suggestions.append("User accounts and authentication")
    if "mobile" not in desc_lower and "native app" not in desc_lower:
        suggestions.append("Native mobile apps (iOS/Android)")
    if len(domains) > 2:
        suggestions.append("Secondary features not listed in must-haves")
    return suggestions[:5]


def _domain_bespoke_questions(
    domains: list[str],
    desc_lower: str,
    *,
    has_existing: bool,
) -> list[BespokeQuestion]:
    questions: list[BespokeQuestion] = []

    if "rss_feeds" in domains or "scraping" in domains:
        questions.append(
            BespokeQuestion(
                id="poll_interval",
                label="How often should feeds be checked or data fetched?",
                type=IntakeFieldType.SELECT,
                options=["Every 5 minutes", "Every 15 minutes", "Hourly", "Daily", "On demand only"],
                default="Every 15 minutes",
                category="domain",
                help="Affects worker scheduling and resource usage.",
            )
        )
        questions.append(
            BespokeQuestion(
                id="feed_sources",
                label="What sources or URLs should it track?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g.\n- https://example.com/rss\n- Hacker News front page\n- Specific subreddits",
                help="List feeds, sites, or endpoints — even roughly. The factory can refine later.",
                category="domain",
                note_type=NoteType.INSTRUCTION,
            )
        )

    if "dashboard" in domains:
        questions.append(
            BespokeQuestion(
                id="data_sources",
                label="Where does the dashboard get its data?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. REST API I provide, PostgreSQL tables, CSV uploads, live metrics endpoint",
                help="Describe inputs — existing APIs, databases, or files the UI should read.",
                category="domain",
                note_type=NoteType.INSTRUCTION,
            )
        )
        questions.append(
            BespokeQuestion(
                id="key_metrics",
                label="What are the 2–4 most important things to show on screen?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. Active users today, error rate, revenue this month, open tasks",
                category="domain",
                note_type=NoteType.FEATURE,
            )
        )

    if "ecommerce" in domains or "billing" in domains:
        questions.append(
            BespokeQuestion(
                id="payments",
                label="Payment processing in v1?",
                type=IntakeFieldType.SELECT,
                options=["No payments in v1", "Stripe integration", "Manual/offline invoicing only"],
                default="No payments in v1",
                category="domain",
            )
        )
        if "ecommerce" in domains:
            questions.append(
                BespokeQuestion(
                    id="catalog_scope",
                    label="What are you selling or tracking?",
                    type=IntakeFieldType.TEXTAREA,
                    placeholder="e.g. Digital downloads, physical products with SKU, subscription tiers",
                    category="domain",
                    note_type=NoteType.FEATURE,
                )
            )

    if "scheduling" in domains:
        questions.append(
            BespokeQuestion(
                id="scheduling_rules",
                label="How should booking/scheduling work?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. 30-min slots, timezone-aware, cancel/reschedule, buffer between meetings",
                category="domain",
                note_type=NoteType.INSTRUCTION,
            )
        )

    if "messaging" in domains:
        questions.append(
            BespokeQuestion(
                id="notifications",
                label="Notification channels needed?",
                type=IntakeFieldType.MULTISELECT,
                options=["Email", "In-app only", "Webhook", "Slack", "None"],
                default="In-app only",
                required=False,
                category="domain",
            )
        )
        if "chat" in desc_lower or "real-time" in desc_lower or "realtime" in desc_lower:
            questions.append(
                BespokeQuestion(
                    id="realtime_requirements",
                    label="Real-time delivery requirements?",
                    type=IntakeFieldType.SELECT,
                    options=[
                        "Polling is fine (every few seconds)",
                        "WebSockets / live updates required",
                        "Async is fine (minutes delay OK)",
                    ],
                    default="Polling is fine (every few seconds)",
                    category="domain",
                )
            )

    if "content" in domains:
        questions.append(
            BespokeQuestion(
                id="content_types",
                label="What types of content will users create or manage?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. Blog posts with markdown, product pages, documentation articles",
                category="domain",
                note_type=NoteType.FEATURE,
            )
        )

    if "search" in domains:
        questions.append(
            BespokeQuestion(
                id="search_scope",
                label="What should users be able to search and filter?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. By title and tags, full-text in body, date range, status",
                category="domain",
                note_type=NoteType.FEATURE,
            )
        )

    if "automation" in domains:
        questions.append(
            BespokeQuestion(
                id="automation_triggers",
                label="What should trigger automated actions?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. New row in database, webhook received, schedule at 9am, manual button",
                category="domain",
                note_type=NoteType.INSTRUCTION,
            )
        )

    if "monitoring" in domains:
        questions.append(
            BespokeQuestion(
                id="alert_conditions",
                label="When should the system alert you?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. Service down, error rate > 5%, disk full, failed job",
                category="domain",
                note_type=NoteType.INSTRUCTION,
            )
        )

    if "integration" in domains:
        questions.append(
            BespokeQuestion(
                id="external_integrations",
                label="Which external services must connect in v1?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. GitHub API, Komga server URL, Stripe, Slack incoming webhook",
                help="Name the services and what data should flow between them.",
                category="domain",
                note_type=NoteType.INSTRUCTION,
            )
        )

    if "files" in domains:
        questions.append(
            BespokeQuestion(
                id="file_handling",
                label="File upload and storage expectations?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. Max 10MB images, store on disk, generate thumbnails, virus scan not needed",
                category="domain",
                note_type=NoteType.INSTRUCTION,
            )
        )

    if "auth_users" in domains or any(w in desc_lower for w in ("team", "organization", "tenant", "multi-user")):
        questions.append(
            BespokeQuestion(
                id="multi_tenancy",
                label="Multi-user / multi-tenant model?",
                type=IntakeFieldType.SELECT,
                options=[
                    "Single user only",
                    "Multiple users, shared data",
                    "Multi-tenant (isolated per organization)",
                ],
                default="Single user only",
                category="domain",
            )
        )

    if "crud_data" in domains and not has_existing:
        questions.append(
            BespokeQuestion(
                id="main_entities",
                label="What are the main things (entities) users manage?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. Projects and tasks, customers and orders, books and shelves",
                help="Name the nouns in your app — these often become database models and UI screens.",
                category="domain",
                note_type=NoteType.FEATURE,
            )
        )

    return questions


def _ambiguity_questions(
    analysis: DescriptionAnalysis,
    description: str,
    *,
    has_existing: bool,
) -> list[BespokeQuestion]:
    questions: list[BespokeQuestion] = []
    desc_lower = description.lower()

    if len(description.strip()) < 80:
        questions.append(
            BespokeQuestion(
                id="clarify_vision",
                label="Expand on your vision — what problem does this solve?",
                type=IntakeFieldType.TEXTAREA,
                help="Your initial description was brief. A few more sentences help the factory scope v1 correctly.",
                placeholder="Describe the workflow end-to-end: who opens it, what they do, what they get out of it.",
                category="vision",
                note_type=NoteType.INSTRUCTION,
            )
        )

    if len(analysis.domains) > 2:
        domain_labels = {
            "rss_feeds": "RSS / feeds",
            "scraping": "Web scraping",
            "dashboard": "Dashboard / analytics",
            "ecommerce": "E-commerce",
            "billing": "Billing / payments",
            "scheduling": "Scheduling",
            "messaging": "Messaging / notifications",
            "content": "Content / CMS",
            "search": "Search",
            "automation": "Automation",
            "monitoring": "Monitoring",
            "integration": "Integrations",
            "auth_users": "Users / auth",
            "files": "File handling",
            "crud_data": "Data management",
        }
        options = [domain_labels.get(d, d.replace("_", " ").title()) for d in analysis.domains[:6]]
        questions.append(
            BespokeQuestion(
                id="priority_focus",
                label="Your idea touches several areas — what is the #1 focus for v1?",
                type=IntakeFieldType.SELECT,
                options=options + ["All equally important"],
                category="vision",
                note_type=NoteType.INSTRUCTION,
            )
        )

    if analysis.reference_apps:
        questions.append(
            BespokeQuestion(
                id="reference_behavior",
                label=f"What specifically should work like {' / '.join(analysis.reference_apps)}?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. Same navigation pattern, similar listing page, but simpler auth",
                default=None,
                category="vision",
                note_type=NoteType.INSTRUCTION,
            )
        )

    if analysis.ui_signal == "web" or analysis.app_type == "fullstack_web":
        if not any(w in desc_lower for w in ("design", "style", "look", "ui", "ux", "layout", "mobile")):
            questions.append(
                BespokeQuestion(
                    id="ui_preferences",
                    label="Any UI or layout preferences?",
                    type=IntakeFieldType.TEXTAREA,
                    placeholder="e.g. Clean admin panel, mobile-first, dark mode, minimal like Linear",
                    required=False,
                    category="technical",
                    note_type=NoteType.INSTRUCTION,
                )
            )

    if has_existing and not any(w in desc_lower for w in ("keep", "extend", "existing", "current", "don't break")):
        questions.append(
            BespokeQuestion(
                id="preserve_existing",
                label="Anything in the current codebase that must not change?",
                type=IntakeFieldType.TEXTAREA,
                placeholder="e.g. Keep existing API routes, don't rename database tables, preserve auth flow",
                required=False,
                category="existing",
                note_type=NoteType.SCOPE_OUT,
            )
        )

    return questions


def analyze_project_description(
    name: str,
    description: str,
    *,
    repo_context: dict[str, Any] | None = None,
) -> DescriptionAnalysis:
    """Parse the user's initial ask and decide what follow-up questions matter."""
    repo_context = repo_context or {}
    desc_lower = description.lower()
    app_type = _detect_app_type(description)
    domains = _detect_domains(desc_lower)
    features = _extract_features_from_description(description)
    user_hint = _extract_user_hint(description)
    auth_signal = _detect_auth_signal(desc_lower)
    persistence_signal = _detect_persistence_signal(desc_lower, repo_context)
    ui_signal = _detect_ui_signal(desc_lower, app_type)
    reference_apps = _extract_reference_apps(description)
    has_existing = bool(repo_context.get("has_existing_app"))

    themes: list[str] = []
    if domains:
        themes.extend(domains[:4])
    if app_type != "fullstack_web":
        themes.append(app_type)

    open_questions: list[str] = []
    if auth_signal == "unclear":
        open_questions.append("Whether users need to log in")
    if persistence_signal == "unclear":
        open_questions.append("How data should be stored long-term")
    if ui_signal == "unclear" and app_type == "fullstack_web":
        open_questions.append("Whether a browser UI is required or API-only is enough")
    if not features and len(description) > 40:
        open_questions.append("Concrete must-have features for v1")
    if not user_hint:
        open_questions.append("Who the primary users are")
    if "integration" in domains or "komga" in desc_lower:
        open_questions.append("External service URLs, credentials, and sync behavior")

    interpretation_parts = [f"**{name}** — {description.strip()[:500]}"]
    if domains:
        interpretation_parts.append(
            "Detected themes: " + ", ".join(d.replace("_", " ") for d in domains[:5])
        )
    if features:
        interpretation_parts.append("Features mentioned: " + "; ".join(features[:5]))
    if has_existing:
        interpretation_parts.append(
            "Will extend the linked repository rather than greenfield scaffold."
        )
    interpretation = "\n".join(interpretation_parts)

    bespoke = _domain_bespoke_questions(domains, desc_lower, has_existing=has_existing)
    bespoke.extend(_ambiguity_questions(
        DescriptionAnalysis(
            app_type=app_type,
            domains=domains,
            themes=themes,
            mentioned_features=features,
            user_hint=user_hint,
            auth_signal=auth_signal,
            persistence_signal=persistence_signal,
            ui_signal=ui_signal,
            reference_apps=reference_apps,
            open_questions=open_questions,
            interpretation=interpretation,
            suggested_out_of_scope=_suggest_out_of_scope(domains, desc_lower),
        ),
        description,
        has_existing=has_existing,
    ))

    # Deduplicate by id
    seen: set[str] = set()
    unique_bespoke: list[BespokeQuestion] = []
    for q in bespoke:
        if q.id not in seen:
            seen.add(q.id)
            unique_bespoke.append(q)

    return DescriptionAnalysis(
        app_type=app_type,
        domains=domains,
        themes=themes,
        mentioned_features=features,
        user_hint=user_hint,
        auth_signal=auth_signal,
        persistence_signal=persistence_signal,
        ui_signal=ui_signal,
        reference_apps=reference_apps,
        open_questions=open_questions,
        interpretation=interpretation,
        suggested_out_of_scope=_suggest_out_of_scope(domains, desc_lower),
        bespoke_questions=unique_bespoke,
    )


def bespoke_to_intake_field(q: BespokeQuestion) -> IntakeField:
    return IntakeField(
        id=q.id,
        label=q.label,
        type=q.type,
        help=q.help,
        placeholder=q.placeholder,
        options=q.options,
        required=q.required,
        default=q.default,
        category=q.category,
        note_type=q.note_type,
        show_when=q.show_when,
        prefill_source=q.prefill_source,
    )
