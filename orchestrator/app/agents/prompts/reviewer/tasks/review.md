## Your task
Review the project for production readiness. Tests passed: $tests_passed.
Enrichment passes completed: $enrichment_passes.

The factory's acceptance evaluator has already verified contract requirements against evidence
(see the acceptance report above). Your job is **quality judgment**, not box-ticking:
- Is the implementation unnecessarily complicated or fragile for what it does?
- Were oversized changes justified?
- Does the app feel **complete and polished**, not a bare scaffold?

Reject if core UX polish is missing unless enrichment passes were exhausted and remaining gaps
are documented.

Write `review.json` with:
- decision: "approve" or "reject"
- checklist: acceptance_verified, tests_passed, dockerfile_present, supervisor_notes_applied,
  change_size_justified (booleans)
- concerns: list of strings
- severity: "low" or "high"
