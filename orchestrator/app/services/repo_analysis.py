"""Static analysis of linked repositories — no LLM tokens required."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from app.workspace.provisioner import normalize_repo_url, repo_display_name

_README_NAMES = ("README.md", "readme.md", "Readme.md", "README.MD")
_IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".next",
    "coverage",
    ".turbo",
}
_SOURCE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".vue",
    ".svelte",
    ".cs",
    ".swift",
}
_MANIFEST_FILES = {
    "package.json": "Node.js",
    "pyproject.toml": "Python (pyproject)",
    "requirements.txt": "Python",
    "Pipfile": "Python (Pipenv)",
    "poetry.lock": "Python (Poetry)",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java (Gradle)",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
}


def _read_text(path: Path, limit: int = 8000) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _count_source_files(repo: Path, *, max_depth: int = 6) -> int:
    count = 0
    if not repo.is_dir():
        return 0

    def walk(path: Path, depth: int) -> None:
        nonlocal count
        if depth > max_depth:
            return
        try:
            entries = list(path.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.name in _IGNORE_DIRS or entry.name.startswith("."):
                continue
            if entry.is_file() and entry.suffix.lower() in _SOURCE_EXTENSIONS:
                count += 1
                if count >= 500:
                    return
            elif entry.is_dir():
                walk(entry, depth + 1)

    walk(repo, 0)
    return count


def _detect_manifests(repo: Path) -> list[str]:
    found: list[str] = []
    for name, label in _MANIFEST_FILES.items():
        if (repo / name).is_file():
            found.append(label)
    return found


def _detect_stack(repo: Path, manifests: list[str]) -> list[str]:
    stack = list(dict.fromkeys(manifests))
    req = _read_text(repo / "requirements.txt", 4000).lower()
    if "fastapi" in req and "FastAPI" not in stack:
        stack.append("FastAPI")
    if "flask" in req and "Flask" not in stack:
        stack.append("Flask")
    if "django" in req and "Django" not in stack:
        stack.append("Django")
    if "pytest" in req and "pytest" not in stack:
        stack.append("pytest")

    package_json = repo / "package.json"
    if package_json.is_file():
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for key, label in (
                ("next", "Next.js"),
                ("react", "React"),
                ("vue", "Vue"),
                ("@angular/core", "Angular"),
                ("svelte", "Svelte"),
                ("express", "Express"),
                ("vite", "Vite"),
            ):
                if key in deps and label not in stack:
                    stack.append(label)
        except (json.JSONDecodeError, OSError):
            pass

    if (repo / "manage.py").is_file() and "Django" not in stack:
        stack.append("Django")
    if not stack and (repo / "app" / "main.py").is_file():
        stack.append("Python")
    return stack


def _has_backend(repo: Path) -> bool:
    if (repo / "app" / "main.py").is_file():
        return True
    if (repo / "manage.py").is_file():
        return True
    for name in ("main.py", "app.py", "server.py", "wsgi.py", "asgi.py"):
        if list(repo.rglob(name)):
            return True
    package_json = repo / "package.json"
    if package_json.is_file():
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
            if pkg.get("scripts") or pkg.get("main"):
                return True
        except (json.JSONDecodeError, OSError):
            pass
    if (repo / "go.mod").is_file() or (repo / "Cargo.toml").is_file():
        return True
    return False


def _has_frontend(repo: Path) -> bool:
    if (repo / "app" / "static" / "index.html").is_file():
        return True
    if (repo / "static" / "index.html").is_file():
        return True
    if list(repo.glob("**/index.html")):
        return True
    for marker in ("next.config.js", "next.config.mjs", "next.config.ts", "vite.config.ts", "vite.config.js"):
        if (repo / marker).is_file() or list(repo.glob(f"**/{marker}")):
            return True
    package_json = repo / "package.json"
    if package_json.is_file():
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if any(k in deps for k in ("react", "vue", "next", "@angular/core", "svelte")):
                return True
        except (json.JSONDecodeError, OSError):
            pass
    return False


def _top_level_summary(repo: Path) -> list[str]:
    entries: list[str] = []
    try:
        for entry in sorted(repo.iterdir(), key=lambda p: p.name.lower()):
            if entry.name in _IGNORE_DIRS:
                continue
            if entry.is_dir():
                entries.append(f"{entry.name}/")
            elif entry.is_file():
                entries.append(entry.name)
    except OSError:
        return entries
    return entries[:24]


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


def _infer_existing_capabilities(analysis: dict[str, Any]) -> str:
    parts: list[str] = []
    if analysis.get("stack"):
        parts.append(f"Stack: {', '.join(analysis['stack'])}")
    if analysis.get("has_backend"):
        parts.append("Backend/server code present")
    if analysis.get("has_frontend"):
        parts.append("Browser UI present")
    if analysis.get("has_tests"):
        parts.append("Tests present")
    if analysis.get("has_dockerfile"):
        parts.append("Docker configuration present")
    if analysis.get("source_file_count", 0) >= 8:
        parts.append(f"{analysis['source_file_count']} source files detected")
    if analysis.get("detected_features"):
        parts.append("README documents existing capabilities")
    return "; ".join(parts) if parts else "Substantial codebase detected"


def infer_intake_defaults(description: str, analysis: dict[str, Any]) -> dict[str, str | list[str]]:
    """Pre-fill intake answers from description, README, and repo structure."""
    from app.services.intake_analysis import analyze_project_description

    readme = analysis.get("readme_excerpt") or ""
    defaults: dict[str, str | list[str]] = {}

    project_analysis = analyze_project_description(
        "project",
        description,
        repo_context=analysis,
    )

    if description.strip():
        defaults["primary_goal"] = description.strip()
        defaults["confirm_interpretation"] = project_analysis.interpretation

    features = analysis.get("detected_features") or []
    desc_features = project_analysis.mentioned_features
    combined_features = desc_features or features
    if combined_features:
        defaults["must_have_features"] = "\n".join(f"- {f}" for f in combined_features[:8])

    if project_analysis.user_hint:
        defaults["target_users"] = project_analysis.user_hint

    auth = _infer_auth_from_readme(readme)
    if auth:
        defaults["authentication"] = auth
    elif project_analysis.auth_signal != "unclear":
        from app.agents.discovery import AUTH_DEFAULTS

        defaults["authentication"] = AUTH_DEFAULTS.get(
            project_analysis.auth_signal, AUTH_DEFAULTS["unclear"]
        )

    if analysis.get("has_frontend"):
        defaults["app_surface"] = "Web browser UI + REST API"
    elif analysis.get("has_backend"):
        defaults["app_surface"] = "REST API only (no UI)"
    elif project_analysis.app_type in ("api_service", "background_worker", "cli_tool"):
        from app.agents.discovery import APP_SURFACE_OPTIONS

        defaults["app_surface"] = APP_SURFACE_OPTIONS.get(project_analysis.app_type, "")

    if project_analysis.persistence_signal != "unclear":
        from app.agents.discovery import PERSISTENCE_DEFAULTS

        defaults["data_persistence"] = PERSISTENCE_DEFAULTS.get(
            project_analysis.persistence_signal, PERSISTENCE_DEFAULTS["unclear"]
        )

    if project_analysis.suggested_out_of_scope:
        defaults["out_of_scope"] = "\n".join(
            f"- {s}" for s in project_analysis.suggested_out_of_scope[:5]
        )

    if analysis.get("has_existing_app"):
        defaults["existing_code_approach"] = "Extend existing code (recommended)"
        defaults["what_works_today"] = _infer_existing_capabilities(analysis)
        defaults["anything_else"] = (
            "Existing codebase detected — extend and integrate with current implementation; "
            "do not rebuild working features unless explicitly requested."
        )
        gaps_parts: list[str] = []
        if description.strip():
            gaps_parts.append(f"From project description: {description.strip()[:500]}")
        if features:
            gaps_parts.append(
                "Preserve README-listed capabilities unless my description asks to change them:\n"
                + "\n".join(f"- {f}" for f in features[:8])
            )
        if gaps_parts:
            defaults["gaps_to_address"] = "\n\n".join(gaps_parts)
        else:
            defaults["gaps_to_address"] = (
                "Continue development on the existing codebase — focus on my project description "
                "without rebuilding what already works."
            )
        defaults["success_criteria"] = (
            "Existing behavior still works; requested changes from my description are implemented "
            "and verifiable in preview/tests."
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
        url = f"https://api.github.com/repos/{owner}/{name}/readme"
        try:
            response = await client.get(url, headers={**headers, "Accept": "application/vnd.github.raw"})
            if response.status_code == 200:
                return response.text[:8000]
        except httpx.HTTPError:
            pass
    return ""


async def fetch_github_repo_meta(repo_url: str, github_token: str | None = None) -> dict[str, Any]:
    """Lightweight GitHub metadata when clone/analysis is incomplete."""
    normalized = normalize_repo_url(repo_url)
    if not normalized:
        return {}
    owner, name = repo_display_name(normalized).split("/", 1)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                f"https://api.github.com/repos/{owner}/{name}",
                headers=headers,
            )
            if response.status_code != 200:
                return {}
            data = response.json()
            return {
                "size_kb": data.get("size") or 0,
                "default_branch": data.get("default_branch") or "main",
                "language": data.get("language"),
                "description": (data.get("description") or "")[:500],
            }
        except httpx.HTTPError:
            return {}


def analyze_repo(repo: Path, *, readme_override: str = "", github_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inspect a cloned repository and return structured context for agents."""
    github_meta = github_meta or {}
    readme = readme_override
    if not readme:
        for name in _README_NAMES:
            readme = _read_text(repo / name)
            if readme:
                break

    has_backend = _has_backend(repo)
    has_frontend = _has_frontend(repo)
    has_tests = (repo / "tests").is_dir() or bool(list(repo.glob("test_*.py"))) or bool(
        list(repo.glob("**/*_test.go"))
    )
    has_docker = (repo / "Dockerfile").is_file() or (repo / "docker-compose.yml").is_file()
    manifests = _detect_manifests(repo)
    source_file_count = _count_source_files(repo)
    top_level = _top_level_summary(repo)

    entry_points: list[str] = []
    for candidate in (
        "app/main.py",
        "main.py",
        "src/main.py",
        "manage.py",
        "server.js",
        "index.js",
        "cmd/main.go",
    ):
        if (repo / candidate).is_file():
            entry_points.append(candidate)
        elif list(repo.glob(f"**/{candidate.split('/')[-1]}"))[:1]:
            found = list(repo.glob(f"**/{candidate.split('/')[-1]}"))[0]
            try:
                entry_points.append(str(found.relative_to(repo)))
            except ValueError:
                entry_points.append(str(found))

    preserve: list[str] = []
    for rel in ("app/", "src/", "tests/", "frontend/", "backend/", "Dockerfile", "requirements.txt", "pyproject.toml", "package.json"):
        if (repo / rel.rstrip("/")).exists():
            preserve.append(rel)

    detected = _extract_readme_features(readme)
    stack = _detect_stack(repo, manifests)

    substantial_by_files = source_file_count >= 8
    substantial_by_manifest = bool(manifests) and source_file_count >= 3
    substantial_by_github = (github_meta.get("size_kb") or 0) >= 100
    has_substantial_codebase = substantial_by_files or substantial_by_manifest or substantial_by_github

    has_existing_app = (
        has_backend
        or has_frontend
        or has_docker
        or has_substantial_codebase
        or bool(manifests)
    )

    continuation_mode = "extend" if has_existing_app else "greenfield"

    return {
        "has_existing_app": has_existing_app,
        "has_substantial_codebase": has_substantial_codebase,
        "continuation_mode": continuation_mode,
        "has_backend": has_backend,
        "has_frontend": has_frontend,
        "has_tests": has_tests,
        "has_dockerfile": has_docker,
        "stack": stack,
        "manifests": manifests,
        "source_file_count": source_file_count,
        "top_level_entries": top_level,
        "readme_excerpt": readme[:4000] if readme else "",
        "detected_features": detected,
        "entry_points": entry_points[:8],
        "preserve_paths": preserve,
        "github_language": github_meta.get("language"),
        "github_description": github_meta.get("description") or "",
    }


def format_repo_analysis_for_prompt(analysis: dict[str, Any] | None) -> str:
    if not analysis or not analysis.get("has_existing_app"):
        return ""

    lines = [
        "## Existing repository (extend — do not rebuild)",
        "The factory linked an **existing codebase**. Your job is to **continue and extend** it.",
        "",
        "**Rules for existing repos:**",
        "- Read existing code, docs, and tests before changing anything.",
        "- Do **not** reimplement routes, models, or UI that already work.",
        "- Only add or modify what intake notes, tasks, or gaps require.",
        "- Match the project's existing stack, conventions, and file layout.",
        "- Prefer incremental commits on the factory work branch.",
        "",
        f"- Continuation mode: {analysis.get('continuation_mode', 'extend')}",
        f"- Stack detected: {', '.join(analysis.get('stack') or []) or 'unknown'}",
        f"- Source files scanned: {analysis.get('source_file_count', 0)}",
        f"- Backend present: {analysis.get('has_backend')}",
        f"- Frontend/UI present: {analysis.get('has_frontend')}",
        f"- Tests present: {analysis.get('has_tests')}",
        f"- Dockerfile present: {analysis.get('has_dockerfile')}",
    ]
    if analysis.get("top_level_entries"):
        lines.append(f"- Top level: {', '.join(analysis['top_level_entries'][:12])}")
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
    if analysis.get("agent_summary"):
        lines.extend(["", "### Agent exploration summary", analysis["agent_summary"]])
    if analysis.get("how_to_progress"):
        lines.extend(["", "### Recommended next steps", analysis["how_to_progress"]])
    return "\n".join(lines)
