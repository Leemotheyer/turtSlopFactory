#!/usr/bin/env python3
"""Delete untagged and stale GHCR versions for turtslopfactory; keep latest/main."""

from __future__ import annotations

import json
import os
import subprocess
import sys

PACKAGE = "turtslopfactory"
OWNER = os.environ.get("GHCR_OWNER", "Leemotheyer")
KEEP_TAGS = {"latest", "main"}


def gh_json(path: str, method: str = "GET") -> object:
    cmd = ["gh", "api", "--method", method, path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def list_versions() -> list[dict]:
    versions: list[dict] = []
    page = 1
    while True:
        batch = gh_json(
            f"/users/{OWNER}/packages/container/{PACKAGE}/versions?per_page=100&page={page}"
        )
        if not batch:
            break
        versions.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return versions


def main() -> int:
    versions = list_versions()
    keep_ids: set[int] = set()
    for version in versions:
        tags = (version.get("metadata") or {}).get("container", {}).get("tags") or []
        if KEEP_TAGS.intersection(tags):
            keep_ids.add(version["id"])

    deleted = 0
    for version in versions:
        vid = version["id"]
        tags = (version.get("metadata") or {}).get("container", {}).get("tags") or []
        if vid in keep_ids:
            print(f"keep {vid} tags={tags}")
            continue
        gh_json(f"/users/{OWNER}/packages/container/{PACKAGE}/versions/{vid}", method="DELETE")
        deleted += 1

    print(f"Pruned {deleted} version(s); kept {len(keep_ids)} tagged release(s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
