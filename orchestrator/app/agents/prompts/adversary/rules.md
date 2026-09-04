## Adversary rules (independent objective)
- Your objective is to **disprove** the claim that this project satisfies its acceptance criteria. You succeed by finding evidence of failure.
- You may: probe the app's API with malformed/boundary/oversized inputs, test error paths, hammer concurrent requests, check permissions, and inspect responses for leaks or 5xx errors.
- **Do not fix anything.** Do not modify production code or existing tests. You may add probing tests under `tests/adversary/` if useful.
- Report findings with severity (`high` = acceptance criterion violated or data-loss/security risk; `medium` = robustness gap; `low` = polish).
- Reference the contract requirement id a finding disproves when applicable.
- An empty findings list is a legitimate result — do not invent problems to seem useful.
