"""Parse free-form agent replies into schema-validated artifacts."""

from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def extract_json_block(text: str) -> str | None:
    """Pull the first JSON object out of an agent reply (fenced or bare)."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    return None


def parse_agent_json(model_cls: type[T], raw: str | None) -> T | None:
    """Validate agent output against ``model_cls``; None when unparseable.

    Accepts raw JSON, fenced JSON, or JSON embedded in prose. Unknown fields
    are ignored by the schemas; missing fields fall back to defaults.
    """
    if not raw:
        return None
    text = raw.strip()

    candidates: list[str] = []
    if text.startswith("{"):
        candidates.append(text)
    block = extract_json_block(text)
    if block and block not in candidates:
        candidates.append(block)

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        try:
            return model_cls.model_validate(data)
        except ValidationError as exc:
            logger.debug("Agent JSON failed %s validation: %s", model_cls.__name__, exc)
            continue
    return None
