#!/usr/bin/env python3
"""E2E: Sonarr-style manga downloader with Mihon-compatible source architecture."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8044"

# Mihon uses extension repos (not bundled sources). Keiyoushi is the primary community repo.
# Popular sources in that ecosystem: MangaDex, ComicK, Mangakakalot, Weeb Central, Asura Scans,
# Toonily, MangaFire, Tumangaonline, etc. MangaDex also has an official REST API.
MIHON_SOURCE_CONTEXT = """
## External sources (Mihon / Tachiyomi model)

Mihon does NOT bundle sources — users add extension repositories. The standard community repo is:
- Keiyoushi: https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json

Representative sources from that ecosystem (implement as pluggable adapters):
- **MangaDex** — use the official MangaDex API (https://api.mangadex.org) as the primary legal source
- **ComicK** — adapter stub + search interface (extension-style)
- **Mangakakalot / Mangakakalot-style** — adapter interface only unless robots.txt allows
- **Weeb Central** — adapter stub
- **Asura Scans, Toonily, MangaFire, Tumangaonline** — register in source catalog; implement at least MangaDex fully

Architecture must mirror Mihon: a **source registry**, **extension metadata** (id, name, lang, baseUrl, version),
and a **SourceProvider** interface: searchSeries, getSeries, listChapters, getChapterPages/download.
Sonarr-like automation: watch list, monitored series, download queue, failed download retry, library folder layout.
""".strip()

PROJECT_DESCRIPTION = f"""
Build **MangaArr** — a self-hosted Sonarr-style manga library manager and downloader with a web UI and REST API.

{MIHON_SOURCE_CONTEXT}

## Sonarr-like core features
- **Library**: tracked series with metadata (title, cover, status, authors, tags, path on disk)
- **Monitor / wanted**: mark series as monitored; auto-detect new chapters
- **Search**: global search across enabled sources; pick result and add to library
- **Download queue**: pending, downloading, completed, failed; retry with backoff
- **Quality / preferences**: prefer source order (MangaDex first), language filter, chapter gap handling
- **Naming & folders**: configurable template e.g. `{{Series Title}}/Chapter {{num}} - {{title}}`
- **History & logs**: download events, source used, bytes saved, errors
- **Scheduler**: periodic refresh of monitored series (configurable interval)
- **Dashboard**: active downloads, recently added, missing chapters, disk usage

## Web UI (multi-page)
- Dashboard, Library, Add Series (search), Queue, History, Settings (sources, paths, schedule)
- Search box with source filter chips (MangaDex, ComicK, etc.)
- Series detail: chapters list, download all / missing, monitor toggle

## REST API
- Full CRUD for library, queue, sources, settings
- `POST /api/search?q=` searches enabled providers
- `POST /api/library/{{id}}/refresh` checks sources for new chapters
- `GET /health` returns 200

## Source implementation requirements
- **MangaDex**: fully working via official API (search, series info, chapter list, download pages/images to library path)
- **At least 2 additional source adapters** registered with stub or partial implementation + unified search aggregation
- Source catalog JSON documenting Mihon-style extensions (id, displayName, repoUrl, supportedLanguages)
- Document Keiyoushi repo URL in README as reference for future extension ports

## Storage & ops
- SQLite for library, queue, settings, download history
- Local filesystem for downloaded chapters (CBZ or folder-per-chapter with images)
- Dockerfile on port 8080, docker-compose.yml, README with setup and API docs
- pytest for API + source adapter tests; acceptance tests named test_r*_*

## Out of scope
- User authentication (single-user internal tool)
- Mobile apps
- Video/anime (manga only)
- Bypassing paywalls or DRM

## Success criteria
- docker compose up --build serves UI on 8080
- Add series via MangaDex search, download at least one chapter to disk, see it in library
- Queue processes jobs; scheduler endpoint or background task checks monitored series
- All tests pass; app deployable via factory preview
""".strip()


def api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def wait_for_discovery(project_id: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        disc = api("GET", f"/api/projects/{project_id}/discovery")
        if disc.get("status") in ("awaiting_user", "submitted", "auto_submitted"):
            return disc
        time.sleep(3)
    raise TimeoutError("Discovery did not complete")


def build_intake_responses(discovery: dict) -> dict:
    defaults = {
        "primary_goal": "Sonarr-style manga library manager with automated chapter downloads from external sources",
        "target_users": "Self-hosted media hoarders / manga readers (single user, no login)",
        "must_have_features": "\n".join(
            [
                "Library with monitored series and Sonarr-like wanted/missing logic",
                "Global search across pluggable sources (MangaDex API + extension-style adapters)",
                "Download queue with retry, history, and configurable folder naming",
                "Background scheduler to refresh monitored series for new chapters",
                "Multi-page web UI: dashboard, library, search, queue, settings",
                "REST API + SQLite + Docker on port 8080",
                "Source registry modeled after Mihon/Keiyoushi extensions (MangaDex, ComicK, Mangakakalot stubs)",
            ]
        ),
        "out_of_scope": "\n".join(
            [
                "Authentication",
                "Anime/video",
                "Mobile apps",
                "DRM bypass",
            ]
        ),
        "app_surface": "Web browser UI + REST API",
        "auth_model": "No auth (single-user / internal tool)",
        "data_storage": "SQLite + local filesystem for downloads",
        "success_criteria": "Search MangaDex, add series, download chapter to disk, queue works, docker compose up on 8080",
        "main_entities": "Series, Chapter, DownloadJob, Source, SourceExtension, Settings, DownloadHistory",
        "external_integrations": "MangaDex official API; Mihon Keiyoushi extension catalog as reference for ComicK, Mangakakalot, Weeb Central, Asura, Toonily",
    }
    responses: dict = {}
    for field in discovery.get("form_fields") or []:
        fid = field["id"]
        if fid in defaults:
            responses[fid] = defaults[fid]
        elif field.get("default"):
            responses[fid] = field["default"]
        elif field["type"] == "multiselect":
            responses[fid] = field.get("options") or []
        else:
            responses[fid] = defaults.get(fid, "As described in the project brief")
    return responses


def poll_project(project_id: str, timeout_hours: float = 8.0) -> None:
    deadline = time.time() + timeout_hours * 3600
    last_state = last_sub = None
    while time.time() < deadline:
        detail = api("GET", f"/api/projects/{project_id}/detail")
        state = detail.get("state")
        substage = (detail.get("pipeline_substage") or {}).get("step")
        running = detail.get("pipeline_running")
        if state != last_state or substage != last_sub:
            print(
                f"[{time.strftime('%H:%M:%S')}] state={state} substage={substage or '-'} "
                f"running={running} failed={detail.get('failed_gate')}/{detail.get('failed_substage')}",
                flush=True,
            )
            last_state, last_sub = state, substage
        if state == "PRODUCTION":
            print(f"DONE {detail.get('preview_url')}")
            return
        if state == "AUTONOMOUSLY_BLOCKED":
            log = api("GET", f"/api/projects/{project_id}/logs/pipeline.log")
            print("BLOCKED — tail:")
            for line in (log.get("content") or "").splitlines()[-40:]:
                print(" ", line)
            raise SystemExit(1)
        time.sleep(25)
    raise TimeoutError("Pipeline timeout")


def main() -> int:
    print("Creating MangaArr (Sonarr-style manga downloader)...")
    project = api(
        "POST",
        "/api/projects",
        {
            "name": "MangaArr Downloader",
            "description": PROJECT_DESCRIPTION,
            "max_enrichment_passes": 1,
        },
    )
    pid = project["id"]
    print(f"Project {pid} state={project['state']}")

    disc = wait_for_discovery(pid)
    if disc.get("status") == "awaiting_user":
        responses = build_intake_responses(disc)
        print(f"Submitting intake ({len(responses)} fields)...")
        api("POST", f"/api/projects/{pid}/discovery/submit", {"responses": responses})

    detail = api("GET", f"/api/projects/{pid}/detail")
    if not detail.get("pipeline_running") and detail.get("state") == "PLANNING":
        api("POST", f"/api/projects/{pid}/run")

    poll_project(pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
