## Your task — product QA on the live preview (enrichment pass $pass_num)
Interact with the factory live preview like a user. Do not start Docker or uvicorn.

Live preview: $upstream
Health: GET $health_path
Audit summary: health_ok=$audit_health_ok, has_ui=$audit_has_html_ui

Probe key endpoints and the HTML UI. Write `product-qa.json` with:
- `passed`: boolean — did this enrichment pass add **meaningful** user-visible value?
- `issues`: list of concrete UX/functionality problems still present
- `suggested_features`: list of substantial improvements worth implementing next (not nits)

**Fail the pass** if the only changes were cosmetic while core flows are still missing.
