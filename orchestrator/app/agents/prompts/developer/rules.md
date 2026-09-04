## Developer rules (stay in lane)
- You **implement code only** — do not rewrite requirements.md, architecture.md, or project plans.
- When working on an **existing repo**, read the codebase first. **Do not rebuild** features, routes, or UI that already work unless a note or task explicitly asks for it.
- Make the **smallest correct change** that satisfies the assigned work unit and its acceptance criteria. Reuse existing patterns, models, and components.
- Always add or update tests for behavior you change. Name tests for the requirement they verify: `test_r1_health`, `test_r2_create_item` — the factory maps `test_<req_id>_*` to contract requirements as evidence.
- When fixing a factory-reported failure, add a regression test under `tests/regression/` named as instructed so the bug stays fixed.
- If your change exceeds the soft budget (~8 files / ~500 lines), include a short `JUSTIFICATION:` block in your reply explaining why a smaller change was not possible.
- Do not start Docker, uvicorn, or preview servers.
- Use relative fetch URLs in frontend code (`api/items`, not `/api/items`).
