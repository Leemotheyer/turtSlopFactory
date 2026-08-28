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
                "- **Continue the linked repository** — do not rebuild working features.",
                "- Preserve existing architecture unless intake explicitly requests a rewrite.",
                f"- Detected stack: {', '.join(repo_analysis.get('stack') or []) or 'see repo'}",
                f"- Source files scanned: {repo_analysis.get('source_file_count', 0)}",
                f"- Backend: {'yes' if repo_analysis.get('has_backend') else 'no'}",
                f"- Frontend: {'yes' if repo_analysis.get('has_frontend') else 'no'}",
                "",
            ]
        )
        what_works = intake.get("what_works_today")
        if what_works:
            lines.extend(["### Already in the repo (preserve)", str(what_works), ""])
        gaps = intake.get("gaps_to_address")
        if gaps:
            lines.extend(["### Gaps to address", str(gaps), ""])
        if repo_analysis.get("detected_features"):
            lines.append("### Already documented in README")
            for feat in repo_analysis["detected_features"][:10]:
                lines.append(f"- {feat}")
            lines.append("")

    must_have = intake.get("must_have_features") or intake.get("primary_goal")
    if must_have:
        label = "Changes requested" if repo_analysis and repo_analysis.get("has_existing_app") else "Must-have (MVP)"
        lines.extend([f"## {label}", str(must_have), ""])

    out_of_scope = intake.get("out_of_scope")
    if out_of_scope:
        lines.extend(["## Out of scope", str(out_of_scope), ""])

    success = intake.get("success_criteria")
    if success:
        lines.extend(["## Acceptance criteria", str(success), ""])

    if repo_analysis and repo_analysis.get("has_existing_app"):
        lines.extend(
            [
                "## Quality bar",
                "- Existing behavior preserved unless explicitly changed in intake",
                "- New/changed features work in the factory live preview",
                "- Tests pass for affected areas",
                "",
            ]
        )
    else:
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
