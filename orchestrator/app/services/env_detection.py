"""Detect env vars a project needs and ensure dashboard placeholders exist."""

from __future__ import annotations

import re
from typing import Iterable

# (pattern, key_name, description)
_ENV_KEY_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bopenai\b", re.I), "OPENAI_API_KEY", "OpenAI API key"),
    (re.compile(r"\banthropic\b|\bclaude\b", re.I), "ANTHROPIC_API_KEY", "Anthropic API key"),
    (re.compile(r"\bstripe\b", re.I), "STRIPE_SECRET_KEY", "Stripe secret key for payments"),
    (re.compile(r"\bsendgrid\b", re.I), "SENDGRID_API_KEY", "SendGrid API key for email"),
    (re.compile(r"\btwilio\b", re.I), "TWILIO_AUTH_TOKEN", "Twilio auth token for SMS/voice"),
    (re.compile(r"\baws\b|\bs3\b", re.I), "AWS_SECRET_ACCESS_KEY", "AWS secret access key"),
    (
        re.compile(r"\bgithub\b.*\btoken\b|\bgh[_\s]?token\b", re.I),
        "GITHUB_TOKEN",
        "GitHub personal access token",
    ),
    (re.compile(r"\bkomga\b", re.I), "KOMGA_BASE_URL", "Komga server base URL (e.g. https://komga.example.com)"),
    (
        re.compile(r"\bkomga\b.*\b(user|login|auth|password|credential)", re.I),
        "KOMGA_USERNAME",
        "Komga username for authenticated API access during testing",
    ),
    (
        re.compile(r"\bkomga\b.*\b(password|credential|auth)", re.I),
        "KOMGA_PASSWORD",
        "Komga password for authenticated API access during testing",
    ),
    (
        re.compile(r"\boauth\b|\bgoogle sign[\s-]?in\b|\bauth0\b|\boidc\b", re.I),
        "OAUTH_CLIENT_ID",
        "OAuth client ID for sign-in flows",
    ),
    (
        re.compile(r"\boauth\b.*\bsecret\b|\bauth0\b|\boidc\b", re.I),
        "OAUTH_CLIENT_SECRET",
        "OAuth client secret for sign-in flows",
    ),
    (
        re.compile(r"\bjwt\b|\bsession secret\b|\bapp secret\b", re.I),
        "JWT_SECRET",
        "JWT or session signing secret",
    ),
    (
        re.compile(r"\bdatabase url\b|\bpostgres(ql)?://|\bmongodb(\+srv)?://", re.I),
        "DATABASE_URL",
        "Database connection URL",
    ),
    (
        re.compile(r"\blogin page\b|\bsign[\s-]?in\b|\bauthentication required\b|\bcredentials\b", re.I),
        "APP_USERNAME",
        "Application login username for preview/testing",
    ),
    (
        re.compile(r"\blogin page\b|\bsign[\s-]?in\b|\bpassword\b|\bcredentials\b", re.I),
        "APP_PASSWORD",
        "Application login password for preview/testing",
    ),
    (
        re.compile(r"\bapi[_\s]?key\b|\bsecret[_\s]?key\b", re.I),
        "API_KEY",
        "API key referenced by the application",
    ),
    (
        re.compile(r"\bbase url\b|\bserver url\b|\bexternal url\b|\bwebhook url\b", re.I),
        "EXTERNAL_BASE_URL",
        "External service base URL the app connects to",
    ),
]


def detect_env_keys_from_text(text: str) -> list[tuple[str, str]]:
    """Return deduplicated (KEY_NAME, description) pairs matched in text."""
    if not text or not text.strip():
        return []
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern, key_name, description in _ENV_KEY_PATTERNS:
        if pattern.search(text) and key_name not in seen:
            found.append((key_name, description))
            seen.add(key_name)
    return found


def detect_env_keys_from_texts(texts: Iterable[str]) -> list[tuple[str, str]]:
    combined = "\n".join(t for t in texts if t)
    return detect_env_keys_from_text(combined)
