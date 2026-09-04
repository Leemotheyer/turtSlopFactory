## Your task — write acceptance tests from the project contract
The contract requirements and acceptance criteria are listed above. Turn **each acceptance
criterion** into an automated pytest test under `tests/acceptance/`.

Rules:
- Name every test `test_<req_id_lowercase>_<short_slug>` (e.g. `test_r1_health_returns_ok`) —
  the factory maps test names to requirements as verification evidence.
- Use `fastapi.testclient.TestClient` against `app.main:app` — do not start servers.
- Test the behavior the criterion describes, including error cases (bad input, missing ids).
- Do not modify production code or existing tests. Only add files under `tests/acceptance/`.
- Keep tests deterministic — no sleeps, no external network calls.

Finish by running `python -m pytest tests/acceptance -q` and fixing any test bugs (not app bugs —
if the app violates a criterion, leave the failing test in place and say so in your reply).
