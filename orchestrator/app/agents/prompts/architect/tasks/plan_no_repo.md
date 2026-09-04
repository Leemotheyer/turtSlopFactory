## Your task
You are a no-repo Cloud Agent. There is no GitHub repository and nothing you write to disk will be synced.

**Ground everything in the Product vision and intake answers above.**

Put BOTH documents in your final reply as markdown headings the factory will copy into `requirements.md` and `architecture.md`:

# Requirements
functional/non-functional requirements, user flows, exclusions, quality bar for a complete v1

# Architecture
stack, API design, UI structure, testing strategy

ALSO include a ```json fenced `project-contract.json` block in your reply — the structured contract the factory verifies against:
```json
{
  "goal": "one-paragraph product goal",
  "requirements": [
    {"id": "R1", "description": "…", "acceptance": ["verifiable behavior"], "priority": "must"}
  ],
  "non_goals": [],
  "decisions": [{"decision": "…", "reason": "…"}]
}
```

Use Python 3.12 + FastAPI, Docker on port 8080, pytest coverage, and a `/health` endpoint.
