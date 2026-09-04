"""Derive verifiable contract requirements from intake answers."""

from __future__ import annotations

import re
from typing import Any

from app.contract import ContractRequirement

# Intake fields that describe product capabilities the factory must deliver.
_INTAKE_CAPABILITY_KEYS: tuple[str, ...] = (
    "must_have_features",
    "primary_goal",
    "success_criteria",
    "gaps_to_address",
    "catalog_scope",
    "content_types",
    "main_entities",
    "external_integrations",
    "key_metrics",
    "app_surface",
)

# Start intake-derived requirement ids above the factory scaffold ids (R1–R3).
_INTAKE_REQ_ID_START = 10

_BULLET_SPLIT_RE = re.compile(r"[\n\r]+|(?:^|\s)[•\-*]\s+|\d+[.)]\s+")


def _split_capability_lines(text: str) -> list[str]:
    if not text or not str(text).strip():
        return []
    raw = str(text).strip()
    parts = _BULLET_SPLIT_RE.split(raw)
    lines: list[str] = []
    for part in parts:
        cleaned = " ".join(part.split()).strip(" ,;")
        if len(cleaned) < 8:
            continue
        if cleaned.lower() in {"not specified", "not specified (auto-submitted)", "n/a", "none"}:
            continue
        lines.append(cleaned)
    if not lines and len(raw) >= 12:
        lines.append(raw[:500])
    return lines


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def intake_capability_lines(intake: dict[str, Any] | None) -> list[str]:
    """Flatten intake answers into distinct product-capability statements."""
    intake = intake or {}
    lines: list[str] = []
    for key in _INTAKE_CAPABILITY_KEYS:
        val = intake.get(key)
        if not val:
            continue
        if isinstance(val, list):
            for item in val:
                lines.extend(_split_capability_lines(str(item)))
        else:
            lines.extend(_split_capability_lines(str(val)))
    return _unique_preserve_order(lines)


def intake_has_product_scope(intake: dict[str, Any] | None) -> bool:
    """True when intake describes specific product capabilities beyond a generic scaffold."""
    return len(intake_capability_lines(intake)) > 0


def requirements_from_intake(intake: dict[str, Any] | None) -> list[ContractRequirement]:
    """Turn intake capabilities into must-priority contract requirements."""
    capabilities = intake_capability_lines(intake)
    requirements: list[ContractRequirement] = []
    for idx, capability in enumerate(capabilities):
        req_num = _INTAKE_REQ_ID_START + idx
        req_id = f"R{req_num}"
        requirements.append(
            ContractRequirement(
                id=req_id,
                description=capability,
                acceptance=[
                    f"The capability works end-to-end in the live staging preview: {capability[:240]}",
                    f"A passing pytest named test_{req_id.lower()}_* demonstrates the behavior",
                ],
                priority="must",
            )
        )
    return requirements


def minimum_enrichment_passes(intake: dict[str, Any] | None, *, configured_max: int) -> int:
    """How many enrichment passes must complete before the project is production-ready."""
    if configured_max <= 0:
        return 0
    if not intake_has_product_scope(intake):
        return 0
    # Rich intake specs need at least two polish passes (core flows + depth).
    cap_count = len(intake_capability_lines(intake))
    if cap_count >= 4:
        return min(configured_max, max(2, configured_max // 2))
    return min(configured_max, 1)
