"""Static analysis of linked repositories — no LLM tokens required."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

from app.workspace.provisioner import normalize_repo_url, repo_display_name

_README_NAMES = ("README.md", "readme.md", "Readme.md", "README.MD")
_BACKEND_MARKERS = (
    ("fastapi", "FastAPI"),
    ("flask", "Flask"),
    ("django", "Django"),
    ("starlette", "Starlette"),
)
_FRONTEND_MARKERS = (
    ("app/static", "static UI"),
    ("frontend/", "frontend app"),
    ("templates/", "HTML templates"),
    ("index.html", "index.html"),
)


def _read_text(path: Path, limit: int = 8000) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _detect_stack(repo: Path) -> list[str]:
    stack: list[str] = []
    req = _read_text(repo / "requirements.txt", 4000).lower()
    if "fastapi" in req:
        stack.append("FastAPI")
    if "flask" in req:
        stack.append("Flask")
    if "django" in req:
        stack.append("Django")
    if "pytest" in req:
        stack.append("pytest")
    if (repo / "package.json").is_file():
        stack.append("Node.js")
    if (repo / "pyproject.toml").is_file():
        stack.append("Python (pyproject)")
    if not stack and (repo / "app" / "main.py").is_file():
        stack.append("Python")
    return stack


def _has_backend(repo: Path) -> bool:
    if (repo / "app" / "main.py").is_file():
        return True
    for name in ("main.py", "app.py", "server.py", "wsgi.py", "asgi.py"):
        if list(repo.rglob(name)):
            return True
    return False


def _has_frontend(repo: Path) -> bool:
    if (repo / "app" / "static" / "index.html").is_file():
        return True
    if (repo / "static" / "index.html").is_file():
        return True
    if list(repo.glob("**/index.html")):
        return True
    return False


def _extract_readme_features(readme: str) -> list[str]:
    features: list[str] = []
    for line in readme.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "• ")):
            text = stripped.lstrip("-*• ").strip()
            if 4 < len(text) < 120:
                features.append(text)
        elif stripped.startswith("## ") and len(stripped) < 80:
            title = stripped[3:].strip()
            if title.lower() not in ("installation", "license", "contributing", "usage", "setup"):
                features.append(title)
    return features[:12]


def _infer_auth_from_readme(readme: str) -> str | None:
    lower = readme.lower()
    if any(w in lower for w in ("oauth", "google sign", "github sign", "sso")):
        return "OAuth / SSO (Google, GitHub, etc.)"
    if "api key" in lower:
        return "API keys only"
    if any(w in lower for w in ("login", "password", "authentication", "sign in")):
        return "Simple login (username/password)"
    return None


def infer_intake_defaults(description: str, analysis: dict[str, Any]) -> dict[str, str | list[str]]:
    """Pre-fill intake answers from README + repo structure (static heuristics)."""
    readme = analysis.get("readme_excerpt") or ""
    defaults: dict[str, str | list[str]] = {}

    if description.strip():
        defaults["primary_goal"] = description.strip()

    features = analysis.get("detected_features") or []
    if features:
        defaults["must_have_features"] = "\n".join(f"- {f}" for f in features[:8])

    auth = _infer_auth_from_readme(readme)
    if auth:
        defaults["authentication"] = auth

    if analysis.get("has_frontend"):
        defaults["app_surface"] = "Web browser UI + REST API"
    elif analysis.get("has_backend"):
        defaults["app_surface"] = "REST API only (no UI)"

    if analysis.get("has_existing_app"):
        defaults["anything_else"] = (
            "Existing codebase detected — extend and integrate with current implementation; "
            "do not rebuild working features unless explicitly requested."
        )

    return defaults


async def fetch_github_readme(repo_url: str, github_token: str | None = None) -> str:
    """Fetch README via GitHub API when the repo is not cloned yet."""
    normalized = normalize_repo_url(repo_url)
    if not normalized:
        return ""
    owner, name = repo_display_name(normalized).split("/", 1)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        for path in ("README.md", "readme.md"):
            url = f"https://api.github.com/repos/{owner}/{name}/readme"
            try:
                response = await client.get(url, headers={**headers, "Accept": "application/vnd.github.raw"})
                if response.status_code == 200:
                    return response.text[:8000]
            except httpx.HTTPError:
                continue
    return ""


def analyze_repo(repo: Path, *, readme_override: str = "") -> dict[str, Any]:
    """Inspect a cloned repository and return structured context for agents."""
    readme = readme_override
    if not readme:
        for name in _README_NAMES:
            readme = _read_text(repo / name)
            if readme:
                break

    has_backend = _has_backend(repo)
    has_frontend = _has_frontend(repo)
    has_tests = (repo / "tests").is_dir() or bool(list(repo.glob("test_*.py")))
    has_docker = (repo / "Dockerfile").is_file()

    entry_points: list[str] = []
    for candidate in ("app/main.py", "main.py", "src/main.py"):
        if (repo / candidate).is_file():
            entry_points.append(candidate)

    preserve: list[str] = []
    for rel in ("app/", "tests/", "Dockerfile", "requirements.txt", "pyproject.toml"):
        if (repo / rel).exists():
            preserve.append(rel)

    detected = _extract_readme_features(readme)
    stack = _detect_stack(repo)

    return {
        "has_existing_app": has_backend or has_frontend or has_docker,
        "has_backend": has_backend,
        "has_frontend": has_frontend,
        "has_tests": has_tests,
        "has_dockerfile": has_docker,
        "stack": stack,
        "readme_excerpt": readme[:4000] if readme else "",
        "detected_features": detected,
        "entry_points": entry_points,
        "preserve_paths": preserve,
    }


def format_repo_analysis_for_prompt(analysis: dict[str, Any] | None) -> str:
    if not analysis or not analysis.get("has_existing_app"):
        return ""

    lines = [
        "## Existing repository (extend — do not rebuild)",
        "The factory linked an **existing codebase**. Your job is to **integrate with and extend** it.",
        "",
        "**Rules for existing repos:**",
        "- Read existing code before changing anything.",
        "- Do **not** reimplement routes, models, or UI that already work.",
        "- Only add or modify what intake notes, tasks, or gaps require.",
        "- Match the project's existing stack and file layout.",
        "",
        f"- Stack detected: {', '.join(analysis.get('stack') or []) or 'unknown'}",
        f"- Backend present: {analysis.get('has_backend')}",
        f"- Frontend/UI present: {analysis.get('has_frontend')}",
        f"- Tests present: {analysis.get('has_tests')}",
        f"- Dockerfile present: {analysis.get('has_dockerfile')}",
    ]
    if analysis.get("entry_points"):
        lines.append(f"- Entry points: {', '.join(analysis['entry_points'])}")
    if analysis.get("preserve_paths"):
        lines.append(f"- Preserve structure under: {', '.join(analysis['preserve_paths'])}")
    if analysis.get("detected_features"):
        lines.append("- README suggests existing capabilities:")
        for feat in analysis["detected_features"][:8]:
            lines.append(f"  - {feat}")
    readme = (analysis.get("readme_excerpt") or "").strip()
    if readme:
        excerpt = readme[:1500] + ("…" if len(readme) > 1500 else "")
        lines.extend(["", "### README excerpt", excerpt])
    return "\n".join(lines)
