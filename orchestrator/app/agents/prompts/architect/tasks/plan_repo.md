## Your task
Create or **refine** project requirements and architecture for a **feature-rich, polished v1** — not a bare-minimum MVP or CRUD demo.

**Think bigger from the start.** The factory will implement what you plan in this pass. If you only specify a thin scaffold, users get a disappointing product. Aim for a product someone would actually want to use on day one.

**Ground everything in the Product vision and intake answers above.** Expand on what the user asked for — add complementary capabilities that make the product feel complete (navigation, settings, search/filter, dashboards, auth where appropriate, error handling, empty states). Do not produce generic boilerplate that ignores the project's stated goal.

When an existing repository is linked, document how to **extend** the current codebase — not replace it.

Write two markdown files in the workspace AND repeat both documents in your final reply:
1. `requirements.md` — functional/non-functional requirements, user flows, exclusions, quality bar
2. `architecture.md` — stack, API design, UI structure, testing strategy (respect existing layout)

Start the reply with `# Requirements` then `# Architecture` so the factory can copy them.

### Scope bar for v1
- Include **at least $min_requirements** distinct `priority: "must"` requirements in the contract — each a real user-facing capability, not "has a health endpoint".
- Cover the **full core workflow** end-to-end: list → create → view → edit → delete where data entities exist.
- Plan **multiple screens or views** (home/dashboard, detail views, settings or preferences) — not a single-page stub.
- Add domain-appropriate depth: search/filter for data apps, auth for multi-user apps, export/history where relevant.
- Only mark features `non_goals` when intake explicitly excludes them.

ALSO write `project-contract.json` in the workspace (and include it in your reply as a ```json fence) — the structured contract the factory verifies against:
```json
{
  "goal": "one-paragraph product goal",
  "users": ["who uses this"],
  "requirements": [
    {
      "id": "R1",
      "description": "Users can …",
      "acceptance": [
        "Concrete observable behavior, e.g. POST /api/x returns 201 and the item appears in GET /api/x",
        "Error case, e.g. malformed payload returns 422 with an actionable message"
      ],
      "priority": "must"
    }
  ],
  "non_goals": ["explicitly out of scope"],
  "constraints": ["technical constraints"],
  "quality_targets": ["measurable quality bars"],
  "security_requirements": ["input validation, authz boundaries, secrets handling"],
  "decisions": [
    {"decision": "…", "reason": "…", "alternatives": ["…"], "tradeoffs": "…"}
  ]
}
```
Acceptance criteria are the factory's definition of done — make each one independently verifiable by a pytest test named `test_<req_id_lowercase>_*` or an HTTP probe.

Ensure `/health` and deployment on port 8080. The factory live preview runs the app — do not document manual docker-compose demos.
