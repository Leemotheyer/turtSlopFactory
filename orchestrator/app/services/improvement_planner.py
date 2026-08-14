"""Generate autonomous improvement ideas for self-propelled development iterations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class Improvement:
    title: str
    description: str
    category: str  # polish | feature | mobile | reliability | ux


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _already_covered(content: str, existing: set[str]) -> bool:
    norm = _normalize(content)
    if not norm:
        return True
    for item in existing:
        if norm in item or item in norm:
            return True
        words = set(norm.split())
        item_words = set(item.split())
        if len(words & item_words) >= min(3, len(words), len(item_words)):
            return True
    return False


def _review_concerns(review_raw: str | None) -> list[str]:
    if not review_raw:
        return []
    try:
        report = json.loads(review_raw)
    except json.JSONDecodeError:
        return []
    concerns = report.get("concerns") or []
    return [c for c in concerns if isinstance(c, str) and c.strip()]


def _baseline_improvements(description: str, iteration: int) -> list[Improvement]:
    """Curated improvements that apply to most web GUI Docker apps."""
    desc = description.lower()
    items: list[Improvement] = []

    if iteration <= 1:
        items.extend(
            [
                Improvement(
                    title="Mobile-responsive layout",
                    description=(
                        "Make the UI mobile-friendly: responsive CSS, touch-friendly controls, "
                        "and readable layouts on phones and tablets."
                    ),
                    category="mobile",
                ),
                Improvement(
                    title="Loading and empty states",
                    description=(
                        "Add loading indicators, empty-state messages, and clear feedback when "
                        "API calls are in progress or return no data."
                    ),
                    category="ux",
                ),
                Improvement(
                    title="Error handling and user feedback",
                    description=(
                        "Surface API errors in the UI with friendly messages; validate forms "
                        "before submit and show inline validation hints."
                    ),
                    category="reliability",
                ),
            ]
        )

    if iteration <= 3:
        items.extend(
            [
                Improvement(
                    title="Dark mode toggle",
                    description=(
                        "Add a dark/light theme toggle persisted in localStorage with "
                        "CSS variables for consistent styling."
                    ),
                    category="polish",
                ),
                Improvement(
                    title="Keyboard navigation and accessibility",
                    description=(
                        "Improve accessibility: focus styles, ARIA labels on interactive elements, "
                        "and keyboard shortcuts for common actions."
                    ),
                    category="ux",
                ),
            ]
        )

    if iteration <= 5:
        items.extend(
            [
                Improvement(
                    title="Search and filter",
                    description=(
                        "Add client-side search or filter for list views so users can quickly "
                        "find items as data grows."
                    ),
                    category="feature",
                ),
                Improvement(
                    title="Export data",
                    description=(
                        "Allow exporting list data to CSV or JSON from the UI for backup "
                        "or offline use."
                    ),
                    category="feature",
                ),
            ]
        )

    if "docker" in desc or iteration >= 2:
        items.append(
            Improvement(
                title="Health and readiness polish",
                description=(
                    "Ensure /health reports version and uptime; add graceful shutdown "
                    "handling and structured logging for container observability."
                ),
                category="reliability",
            )
        )

    if iteration >= 4:
        items.extend(
            [
                Improvement(
                    title="Performance optimizations",
                    description=(
                        "Profile slow endpoints; add caching headers for static assets, "
                        "pagination for large lists, and debounced search inputs."
                    ),
                    category="polish",
                ),
                Improvement(
                    title="Documentation and README",
                    description=(
                        "Expand README with setup, API examples, environment variables, "
                        "and screenshots or usage notes for homelab deploy."
                    ),
                    category="polish",
                ),
            ]
        )

    return items


def plan_improvements(
    *,
    description: str,
    notes: list[dict],
    iteration: int,
    review_artifact: str | None = None,
    max_items: int = 2,
) -> list[Improvement]:
    """
    Propose the next batch of improvements for a self-propelled iteration.

    Returns up to max_items improvements not already present in project notes.
    """
    existing: set[str] = set()
    for note in notes:
        content = note.get("content") or ""
        existing.add(_normalize(content))

    candidates: list[Improvement] = []

    for concern in _review_concerns(review_artifact):
        if not _already_covered(concern, existing):
            candidates.append(
                Improvement(
                    title=f"Address review: {concern[:60]}",
                    description=concern,
                    category="reliability",
                )
            )

    for note in notes:
        if note.get("type") != "feature":
            continue
        content = (note.get("content") or "").strip()
        if content and not _already_covered(content, existing):
            candidates.append(
                Improvement(
                    title=f"Complete feature: {content[:48]}",
                    description=content,
                    category="feature",
                )
            )

    offset = (iteration - 1) * max_items
    baseline = _baseline_improvements(description, iteration)
    for item in baseline[offset : offset + max_items * 2]:
        if not _already_covered(item.description, existing):
            candidates.append(item)

    seen: set[str] = set()
    unique: list[Improvement] = []
    for item in candidates:
        key = _normalize(item.description)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique[:max_items]
