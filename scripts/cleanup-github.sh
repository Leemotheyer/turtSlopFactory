#!/usr/bin/env bash
# Remove merged/agent branches and prune GHCR package versions.
# Requires: git, gh (authenticated with repo + packages delete scope)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Fetching remotes"
git fetch --prune origin
git checkout main
git pull origin main

echo "==> Deleting remote branches except main"
while IFS= read -r branch; do
  [[ -z "$branch" ]] && continue
  echo "  delete origin/$branch"
  git push origin --delete "$branch" || true
done < <(git branch -r | sed 's|origin/||' | grep -v '^HEAD$' | grep -v '^main$')

echo "==> Deleting local branches except main"
while IFS= read -r branch; do
  [[ -z "$branch" || "$branch" == "main" ]] && continue
  git branch -D "$branch" || true
done < <(git branch | sed 's/^[* ] //')

echo "==> Closing open pull requests (needs gh auth with pull request write)"
open_prs="$(gh pr list --state open --json number --jq '.[].number' || true)"
if [[ -n "$open_prs" ]]; then
  while IFS= read -r n; do
    [[ -z "$n" ]] && continue
    gh pr close "$n" || true
  done <<< "$open_prs"
else
  echo "  none"
fi

echo "==> Pruning GHCR package versions (keeps latest + main)"
python3 scripts/prune-ghcr-versions.py

echo "Done. Remaining branches:"
git branch -a
