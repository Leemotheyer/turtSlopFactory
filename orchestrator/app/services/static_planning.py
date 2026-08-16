"""Static requirements draft from intake — reduces architect token usage."""

from __future__ import annotations

from typing import Any


def draft_requirements_from_context(
    name: str,
    description: str,
    intake: dict[str, Any] | None = None,
    repo_analysis: dict[str, Any] | None = None,
) -> str:
    """Generate a requirements.md draft without an LLM."""
    intake = intake or {}
    lines = [
        f"# Requirements — {name}",
        "",
        "## Product vision",
        description.strip() or "(See intake answers below)",
        "",
    ]

    if intake:
        lines.append("## Intake specification")
        for key, val in intake.items():
            if isinstance(val, list):
                val = ", ".join(val)
            if val:
                label = key.replace("_", " ").title()
                lines.append(f"### {label}")
                lines.append(str(val))
                lines.append("")

    if repo_analysis and repo_analysis.get("has_existing_app"):
        lines.extend(
            [
                "## Existing codebase constraints",
                "- **Extend the linked repository** — do not rebuild working features.",
                "- Preserve existing architecture unless a supervisor note explicitly requests a rewrite.",
                f"- Detected stack: {', '.join(repo_analysis.get('stack') or []) or 'see repo'}",
                f"- Backend: {'yes' if repo_analysis.get('has_backend') else 'no'}",
                f"- Frontend: {'yes' if repo_analysis.get('has_frontend') else 'no'}",
                "",
            ]
        )
        if repo_analysis.get("detected_features"):
            lines.append("### Already documented in README")
            for feat in repo_analysis["detected_features"][:10]:
                lines.append(f"- {feat}")
            lines.append("")

    must_have = intake.get("must_have_features") or intake.get("primary_goal")
    if must_have:
        lines.extend(["## Must-have (MVP)", str(must_have), ""])

    out_of_scope = intake.get("out_of_scope")
    if out_of_scope:
        lines.extend(["## Out of scope", str(out_of_scope), ""])

    success = intake.get("success_criteria")
    if success:
        lines.extend(["## Acceptance criteria", str(success), ""])

    lines.extend(
        [
            "## Quality bar",
            "- All core flows work in the factory live preview",
            "- pytest coverage for API behavior",
            "- Loading, empty, and error states in the UI",
            "- `/health` returns HTTP 200",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"
