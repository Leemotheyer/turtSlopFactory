## Your task — user perspective review (end of cycle $cycle_label)
You are reviewing this product **as an end user**, not as a developer. Imagine you just discovered this app and want to use it for real.

Live preview: $upstream
Health: GET $health_path
Audit: health_ok=$audit_health_ok, has_ui=$audit_has_html_ui

### What to do
1. Open and exercise the live preview URL — click through the UI, try core flows, note what feels broken or missing.
2. Read `requirements.md` and intake capabilities — note gaps between what was promised and what you experienced.
3. Think broadly: bugs, missing features, confusing UX, cleanup/refactor opportunities, expanded functionality, UI rework.

### Output
Write `user-perspective-review.json` in the workspace AND include the same JSON in your reply:
```json
{
  "passed": true,
  "summary": "One paragraph — how the product feels to a real user right now",
  "suggestions": [
    {
      "title": "Short actionable title",
      "description": "What to change and why a user would care",
      "category": "bug_fix",
      "priority": "high"
    }
  ],
  "notes": "optional extra context"
}
```

**Categories:** `bug_fix`, `feature`, `cleanup`, `ui`, `expansion`, `other`
**Priorities:** `high`, `medium`, `low`

Propose **at least 5** concrete suggestions when possible — be creative and ambitious. These feed the **next improvement cycle**, so think about what would make the product noticeably better.

This review is **non-blocking** — always set `passed: true`. Do not start Docker or uvicorn.
