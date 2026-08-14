"""Plan parallel developer work streams from project context."""

import re
from dataclasses import dataclass


@dataclass
class WorkUnit:
    stream: str  # backend | frontend | feature
    title: str
    description: str
    feature_id: str | None = None
    feature_content: str | None = None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())[:32].strip("-")
    return slug or "feature"


def plan_parallel_work(notes: list[dict], description: str = "") -> list[WorkUnit]:
    """Build independent work units that can run in parallel."""
    units: list[WorkUnit] = [
        WorkUnit(
            stream="backend",
            title="Backend API",
            description="Implement FastAPI routes, models, and server logic",
        ),
        WorkUnit(
            stream="frontend",
            title="Frontend UI",
            description="Implement static web UI and client-side interactions",
        ),
    ]

    seen_slugs: set[str] = set()
    for i, note in enumerate(notes):
        if note.get("type") != "feature":
            continue
        content = (note.get("content") or "").strip()
        if not content:
            continue
        slug = _slugify(content)
        if slug in seen_slugs:
            slug = f"{slug}-{i}"
        seen_slugs.add(slug)
        units.append(
            WorkUnit(
                stream="feature",
                title=f"Feature: {content[:48]}{'…' if len(content) > 48 else ''}",
                description=content,
                feature_id=slug,
                feature_content=content,
            )
        )

    # Heuristic: API-only specs skip dedicated frontend agent
    desc_lower = description.lower()
    if any(kw in desc_lower for kw in ("api only", "api-only", "no ui", "no frontend", "headless")):
        units = [u for u in units if u.stream != "frontend"]

    return units


def work_plan_to_dict(units: list[WorkUnit], concurrency: dict | None = None) -> dict:
    payload: dict = {
        "units": [
            {
                "stream": u.stream,
                "title": u.title,
                "description": u.description,
                "feature_id": u.feature_id,
            }
            for u in units
        ]
    }
    if concurrency:
        payload["concurrency"] = concurrency
    return payload


def _batch_list(items: list[WorkUnit], batch_count: int) -> list[list[WorkUnit]]:
    if batch_count <= 0:
        return [items]
    batches: list[list[WorkUnit]] = [[] for _ in range(batch_count)]
    for index, item in enumerate(items):
        batches[index % batch_count].append(item)
    return [batch for batch in batches if batch]


def optimize_work_units(units: list[WorkUnit], max_parallel: int) -> list[WorkUnit]:
    """Consolidate work when the plan would queue too many agents."""
    if max_parallel < 1:
        max_parallel = 1
    if len(units) <= max_parallel * 2:
        return units

    backends = [u for u in units if u.stream == "backend"]
    frontends = [u for u in units if u.stream == "frontend"]
    features = [u for u in units if u.stream == "feature"]

    result: list[WorkUnit] = []
    if backends:
        result.append(backends[0])
    if frontends:
        result.append(frontends[0])

    feature_slots = max(1, max_parallel - len(result))
    if not features:
        return result

    for index, batch in enumerate(_batch_list(features, feature_slots)):
        if len(batch) == 1:
            result.append(batch[0])
            continue
        contents = [f.feature_content or f.description for f in batch]
        result.append(
            WorkUnit(
                stream="feature",
                title=f"Feature batch ({len(batch)} items)",
                description="Implement the following features:\n" + "\n".join(f"- {c}" for c in contents),
                feature_id=f"batch-{index}",
                feature_content="\n".join(contents),
            )
        )
    return result
