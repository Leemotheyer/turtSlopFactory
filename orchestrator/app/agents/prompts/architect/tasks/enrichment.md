## Autonomous enrichment pass $enrichment_pass/$max_passes
The app has a **working live preview**. Each pass ships **milestone expansion(s)** only — substantial new capabilities.

$theme_hint

**Milestone vs polish (important)**
- $milestone_rule
- Mark smaller UX fixes, hardening, and quality tweaks as `tier: "polish"` — they are **recorded for the next improvement cycle** and are **not implemented in this pass** (same as user review suggestions).
- Only `tier: "milestone"` features are built now.

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
  "quality_issues": ["list of UX or reliability problems observed — deferred to next cycle"],
  "stop_reason": null
}
```

Rules:
- $milestone_count_rule (max **$max_features** features in the plan; only milestones are implemented now).
- Milestones must be **bold, creative big ideas** — new feature areas, major workflows, or significant product expansion.
- Polish features capture UX tweaks, error states, responsive fixes, and test gaps for the **next** cycle backlog — do not expect them to be coded this pass.
- Every description must list concrete deliverables (routes, UI screens, states, tests) — not vague "improve UX".
- Mark milestone(s) `tier: "milestone"`; mark polish-only items `tier: "polish"`.
- Mark `uncertain` only for **new** capabilities that are **not** listed in intake form answers and may expand scope (payments, OAuth, email/SMS, multi-tenant admin, ML, etc.).
- Anything described in intake (`must_have_features`, `success_criteria`, `primary_goal`, etc.) is **always `in_scope`** — never mark it `uncertain` and never defer it.
- Mark `out_of_scope` when it clearly contradicts supervisor notes or the intake `out_of_scope` field.
- Set `stop_reason` only when the app is genuinely production-ready and no worthwhile improvements remain.
- Do NOT replan from scratch — iterate on the running product.
- You **cannot** reach the private preview URL from Cursor Cloud. Use the audit summary above and existing code/docs only.
- Do **NOT** write requirements.md, architecture.md, or a greenfield project plan. Do **NOT** use plan mode.
- Your entire reply must be the JSON object (optionally wrapped in a ```json fence). No markdown architecture documents.
