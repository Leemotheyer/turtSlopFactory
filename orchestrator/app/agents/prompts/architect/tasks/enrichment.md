## Autonomous enrichment pass $enrichment_pass/$max_passes
The app has a **working live preview**. Each pass combines **one milestone expansion** with **polish improvements**.

$theme_hint

**Milestone vs polish**
- Include **exactly one** `tier: "milestone"` feature — a substantial new capability, major feature area, or meaningful product expansion users would notice immediately.
- Include up to **$max_polish** `tier: "polish"` features — smaller UX fixes, hardening, and quality improvements.
- Milestones should add new usefulness (new flows, feature areas, integrations). Polish items refine what already exists.

Preview audit:
- Health OK: $audit_health_ok
- HTML UI detected: $audit_has_html_ui
- Issues found: $audit_issues

Write `enrichment-plan.json` in the workspace AND include the same JSON in your reply:
```json
{
  "features": [
    {
      "id": "slug",
      "title": "Short title",
      "description": "Detailed scope: backend routes, frontend screens, validation, tests, and what the user will see",
      "scope": "in_scope | uncertain | out_of_scope",
      "priority": "high | medium | low",
      "tier": "milestone | polish"
    }
  ],
  "quality_issues": ["list of UX or reliability problems observed"],
  "stop_reason": null
}
```

Rules:
- Propose **exactly one milestone** plus up to **$max_polish** polish features (max **$max_features** total).
- The milestone must be a **big idea** — new feature area, major workflow, or significant expansion of usefulness.
- Polish features are smaller improvements: UX tweaks, error states, responsive fixes, test coverage gaps.
- Every description must list concrete deliverables (routes, UI screens, states, tests) — not vague "improve UX".
- Mark exactly one feature `tier: "milestone"`; mark all others `tier: "polish"`.
- Mark `uncertain` only for **new** capabilities that are **not** listed in intake form answers and may expand scope (payments, OAuth, email/SMS, multi-tenant admin, ML, etc.).
- Anything described in intake (`must_have_features`, `success_criteria`, `primary_goal`, etc.) is **always `in_scope`** — never mark it `uncertain` and never defer it.
- Mark `out_of_scope` when it clearly contradicts supervisor notes or the intake `out_of_scope` field.
- Set `stop_reason` only when the app is genuinely production-ready and no worthwhile improvements remain.
- Do NOT replan from scratch — iterate on the running product.
- You **cannot** reach the private preview URL from Cursor Cloud. Use the audit summary above and existing code/docs only.
- Do **NOT** write requirements.md, architecture.md, or a greenfield project plan. Do **NOT** use plan mode.
- Your entire reply must be the JSON object (optionally wrapped in a ```json fence). No markdown architecture documents.
