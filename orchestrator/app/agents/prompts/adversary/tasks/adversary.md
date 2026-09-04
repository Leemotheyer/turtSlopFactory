## Your task — disprove the acceptance claims
You are the adversarial verifier. The implementer claims this project satisfies the contract
requirements listed above. **Your objective is to find evidence that it does not.**

Live preview (staging): $upstream
Health: GET $health_path

Attack surface (stay within the app — no external targets):
- Malformed and boundary inputs: wrong types, empty payloads, oversized bodies, invalid ids
- Error handling: does anything return a 5xx or leak a stack trace?
- Concurrency: rapid parallel writes to the same resource
- Permissions/validation: can you bypass documented constraints?
- Contract violations: pick each requirement's acceptance criteria and try to break them

Do NOT fix anything. Do NOT modify production code or existing tests.

Write `adversary-report.json` in the workspace AND include the same JSON in your reply:
```json
{
  "findings": [
    {
      "severity": "high | medium | low",
      "requirement_id": "R2",
      "description": "What is broken and why it violates the criteria",
      "reproduction": "Exact request/steps to reproduce"
    }
  ],
  "notes": "What you probed and what held up"
}
```
`high` severity = an acceptance criterion is violated, data can be lost/corrupted, or a security
boundary fails. An empty findings list is a valid result.
