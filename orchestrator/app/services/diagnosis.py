"""Deterministic failure diagnosis: classify before spending a fix attempt.

The cheapest rung of the failure ladder. Classifies a gate failure as
``infra`` (environment/tooling — retry, don't change code), ``test``
(test harness problems), or ``app`` (the code is wrong — developer fix).
"""

from __future__ import annotations

import re

_INFRA_PATTERNS = (
    r"docker daemon",
    r"cannot connect to the docker",
    r"no space left on device",
    r"port is already allocated",
    r"address already in use",
    r"connection refused.*(?:redis|postgres|5432|6379)",
    r"read timed out",
    r"timeout.*(?:pull|registry|network)",
    r"temporary failure in name resolution",
    r"toomanyrequests",
    r"pip install.*(?:timed out|connectionerror|temporary failure)",
    r"no cursor cloud agent slots",
    r"cursor cloud capacity",
    r"cursor cloud create timed out",
    r"docker is required for live preview",
    r"oserror: \[errno 28\]",
    r"could not clone",
)

_TEST_PATTERNS = (
    r"error(?:s)? collecting",
    r"no tests ran",
    r"fixture .* not found",
    r"importerror while importing test module",
)

_APP_PATTERNS = (
    r"assertionerror",
    r"traceback \(most recent call last\)",
    r"modulenotfounderror",
    r"syntaxerror",
    r"indentationerror",
    r"nameerror",
    r"typeerror",
    r"attributeerror",
    r"http/1\.[01]\" 5\d\d",
    r"failed.*health check",
    r"health check failed",
)


def diagnose_failure(
    failure_text: str,
    *,
    logs_tail: str = "",
    gate: str | None = None,
    substage: str | None = None,
) -> dict:
    """Classify a failure; returns {error_class, hint, matched}."""
    corpus = f"{failure_text}\n{logs_tail}".lower()

    for pattern in _INFRA_PATTERNS:
        if re.search(pattern, corpus):
            return {
                "error_class": "infra",
                "hint": f"Environment/tooling failure (matched '{pattern}') — retry without code changes",
                "matched": pattern,
            }

    for pattern in _TEST_PATTERNS:
        if re.search(pattern, corpus):
            return {
                "error_class": "test",
                "hint": f"Test harness problem (matched '{pattern}') — fix test collection/imports",
                "matched": pattern,
            }

    for pattern in _APP_PATTERNS:
        if re.search(pattern, corpus):
            return {
                "error_class": "app",
                "hint": f"Application defect (matched '{pattern}') — developer fix needed",
                "matched": pattern,
            }

    # Deploy-flavored gates default to infra-leaning only with clear signals;
    # otherwise assume the app is at fault (safe default: run the fix loop).
    return {
        "error_class": "app",
        "hint": "Unclassified failure — treating as application defect",
        "matched": None,
    }
