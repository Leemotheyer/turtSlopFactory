# turtSlopFactory — Development Plan

> **Status: implemented.** Phases 0–5 and the opt-in parts of Phase 6 (socket-proxy
> overlay, preview resource limits) shipped together on this branch. The container split
> (6.3) remains deliberately out of scope. See `docs/ARCHITECTURE.md` for the resulting
> architecture and `benchmarks/` + `scripts/run_benchmarks.py` for the evaluation harness.

This plan is the result of reviewing the "fundamental improvements" proposal against the
actual codebase. It records what the proposal got right, what it got wrong or misjudged,
what it missed entirely, and a concrete phased plan to follow.

The proposal's core thesis is adopted unchanged:

> Move from "give agents a task and let them execute a pipeline" toward "give agents a
> measurable outcome, maintain persistent engineering state, and make every change prove
> that it improved the state."

State, evidence, verification, recovery, and measurement become the primitives. Agents are
workers against those primitives, not the primitives themselves.

---

## Part 1 — Where the codebase actually is

The proposal was written at arm's length. Before deciding anything, here is the ground
truth that the plan is built on:

| Area | Current reality |
|------|-----------------|
| Pipeline | One hardcoded linear sequence in `PipelineExecutor.run_pipeline` (`orchestrator/app/pipeline/executor.py`, ~2,380 lines, single class). Gate names drift from what stages do: the `UNIT_TESTING` gate runs integration tests, `INTEGRATION_TESTING` runs the docker build, `DOCKER_BUILD` runs staging deploy. |
| Failure handling | Exists and is decent: gate failure → `DIAGNOSING` (transient, no actual diagnosis) → `FIXING` (developer agent gets failure text) → re-enter failed gate, capped at `max_fix_attempts=5` → `AUTONOMOUSLY_BLOCKED`. |
| Spec | Free text in `projects.description`, refined by a dynamic intake form. `project.contract.yaml` exists but only supplies a healthcheck path/port to the preview (`services/preview_spec.py`). |
| Review | The "reviewer" is near-vacuous: `local_runner.py` checks that `requirements.md`/`architecture.md`/`Dockerfile` files *exist* and that the tests-passed flag is set. A Cursor-backed reviewer can run, but the deterministic checklist can override its rejection. |
| Tester | Always the deterministic local runner (`_CURSOR_ROLES` excludes tester). It runs host-side pytest, HTTP health probes, and HTML heuristics ("product QA", "mobile check"). No LLM ever tries to exercise or break the app. |
| Memory | Workspace `metadata.json` + markdown artifacts + notes + events + progress entries. No structured record of decisions, failures across runs, known bugs, or requirements. |
| Prompts | Hardcoded Python strings (`agents/prompt_builder.py` ~320 lines, `agents/rules/`). No versioning. Agent JSON output is parsed with regex extraction + ad-hoc `json.loads`. |
| Deployment | Docker build via host socket, staging = preview container with built image, "production" = a promote flag + `DeploymentRow`; same container/URL. **No rollback.** Self-propelling post-production cycles exist. |
| Human-in-the-loop | Already good: non-blocking input requests with defaults + 5-min timeout, intake gate, REVIEW→promote gate, merge-to-main gate, notes that trigger feedback iterations, `AUTONOMOUSLY_BLOCKED` escalation. |
| Metrics | Events and progress entries only. No cost/token accounting (except a per-cycle budget in self-propelling), no iteration/outcome KPIs. |
| Schema | `Base.metadata.create_all` on boot. New tables appear automatically; **new columns on existing tables silently do not**. No migration mechanism. |
| Factory tests | 45 pytest modules (~3,600 lines) for the orchestrator; CI runs them plus a dashboard build. Zero dashboard tests. |
| Existing repos | Recently added: continue-existing-GitHub-repo mode, repo analysis + agent repo exploration, isolated `factory/*` branches, merge-on-approval. |

Two structural constraints the proposal didn't know about:

1. **`executor.py` is a God class.** Nearly every proposed feature lands in it. Decomposing
   it is a precondition, not a nice-to-have.
2. **No migration story.** Persistent engineering state means new tables *and* new columns.
   `create_all` handles the former only. A lightweight migration mechanism must come first.

---

## Part 2 — Verdict on the 30 proposals

### Adopted as core direction (the backbone of this plan)

| # | Proposal | Verdict |
|---|----------|---------|
| 1 | Project Contract with acceptance criteria | **Adopt.** The single highest-leverage change. Everything downstream (evaluation, adversary, evidence, health) needs an external definition of "good". Extends the existing `project.contract.yaml` seed rather than inventing a new file. |
| 29 | Requirement → evidence graph | **Adopt, merged with #14.** This is what replaces the file-existence checklist. Every requirement links to implementation, tests, and recorded probe results. |
| 14 | Don't let the AI judge its own success | **Adopt.** Implemented as an acceptance evaluator that reads the contract + evidence, not the coder's claims. |
| 2, 13 | Persistent engineering state; decision database | **Adopt.** Decisions, failure records, and known issues as DB tables with write paths from the pipeline and bounded read paths into prompts. |
| 5 | Adversarial verification | **Adopt, sequenced after the contract exists.** An adversary needs acceptance criteria to falsify; building it first would give it nothing to attack. |
| 6 | Tests as first-class assets, bug → regression test | **Adopt.** Test taxonomy in generated repos + enforced regression-test-per-fixed-failure. |
| 22 | Version prompts like code | **Adopt.** Prompts are already centralized, which makes extraction to versioned files cheap. Record prompt versions on every run. |
| 16, 21 | Outcome metrics; build manifests | **Adopt.** Per-run metrics (iterations, fix attempts, human interventions, outcome) and a manifest per successful build. |
| 23 | Agent evaluation harness | **Adopt.** The existing deterministic `local` backend is a ready-made foundation for pipeline-level regression benchmarks; add real-backend scoring on top. |
| 18 | Automatic rollback | **Adopt.** Cheap: `deployments` already records image tags per environment. Rollback = redeploy previous tag + an observation window after deploy. |

### Adopted with significant modification

| # | Proposal | Modification and why |
|---|----------|----------------------|
| 3 | Feedback-control orchestrator | The control loop skeleton (fail → diagnose → fix → retry → block) **already exists**. The missing piece is the *Evaluate* step — measuring output against an objective. That is exactly the acceptance evaluator from #1/#14. No orchestrator rewrite; the loop gets a real evaluation stage instead. |
| 4 | Epistemic agent roles | Roles already exist (discovery/architect/developer/tester/reviewer). The real gap is **depth, not breadth**: the tester is a deterministic script and the reviewer checks file existence. Deepen those two before adding any new roles. Skip "optimizer" and "release agent" — YAGNI. Add exactly one new role: the adversary. |
| 7 | Change budgets | **Soften.** Hard budgets cause thrash and gaming (splitting one change into eight to fit a file cap). Instead: record diff stats per work unit as evidence, flag oversized changes, require the agent to justify them in its output. The reviewer sees the justification. No hard rejection. |
| 9, 10 | Codebase map, impact analysis | **Extend what exists.** `repo_analysis` + `repo_exploration` already produce structural summaries. Make the output a cached, structured system map, and add a deterministic Python import-graph for impact radius. This matters most for the recently added continue-existing-repo mode; greenfield generated apps are small enough that a full impact system is premature. |
| 11 | Separate discovery from execution | Largely exists (`DISCOVERY` state, repo analysis artifacts, intake). The change is to make discovery outputs **cached structured artifacts refreshed on merge**, not a new pipeline phase. |
| 12 | Four-level memory hierarchy | Adopt levels 1–3 (working = context dict, project = contract/decisions/map, failure = failure records). **Defer level 4** (cross-project organizational memory) until per-project memory has proven its value. Speculative. |
| 15 | Quantitative project health | Adopt, but **only as a derivation of the evidence graph** — % of requirements with verified evidence, test status, deployment status. No standalone scores that aren't backed by recorded evidence, which the proposal itself insists on. |
| 17 | Exception-based supervision | Mostly exists. The addition worth making: a **risk tier** on input requests — destructive/irreversible actions (data-losing migration, force-push, secrets exposure) get no default-and-timeout; they block until answered. |
| 24 | Failure ladder | Partially exists (retry with failure text → blocked). Add the missing cheap rung: make `DIAGNOSING` real — a bounded log-inspection/diagnostic step that classifies the failure (infra vs app vs test) before spending a developer fix attempt. `PreviewLaunch.failure_kind` already hints at this pattern. |
| 26 | Git history in agent context | Adopt as a small prompt/context addition for existing-repo mode (recent `git log`, `git log -S` on touched symbols). Cheap. |
| 27 | Simulation before implementation | `work-plan.json` already exists. Instead of a new simulation stage, add a deterministic **coverage check**: every contract requirement must map to a work unit, or planning fails before any code is written. |
| 28 | Feature-complete vs code-complete | Adopt as a definition, not a feature: "feature complete" = the requirement's acceptance criteria verified against the **live staging preview**. Falls out of #1 + #29 with zero extra machinery. |

### Deferred or dropped

| # | Proposal | Verdict and why |
|---|----------|-----------------|
| 19 | Split the single container | **Defer.** The one-container, one-command install is a deliberate product feature for self-hosters, and supervisord already separates the internal processes. Splitting now imposes migration pain on existing installs for little near-term capability gain. Revisit after the evidence/verification work, if scaling actually demands it. |
| 20 | Dedicated build executor | **Defer the full version; take the cheap wins now.** Full signed-request build isolation is a large subsystem. Near-term: put a docker-socket proxy (endpoint-scoped) in front of the socket, and enforce CPU/memory/network limits on preview and build containers. That captures most of the risk reduction at ~5% of the cost. |
| 25 | Full deterministic tool belt | **Mostly drop.** Cursor-backed agents bring their own tools (search, git, shell). Factory-side deterministic tooling should be limited to what *evaluation* needs: test runner (exists), import graph (#10), diff stats (#7). Building a parallel tool platform duplicates the agent backend. |
| 8 | "Smallest successful change" principle | **Fold in, not a feature.** Becomes a prompt-rules line plus the diff-stat evidence from #7. Nothing else to build. |
| 30 | Target architecture diagram | Adopted in spirit — it is what the phases below sum to. Not a separate work item. |

### What the proposal missed (added to the plan)

1. **Executor decomposition** — precondition for everything (Phase 0).
2. **Schema migrations** — precondition for persistent state (Phase 0).
3. **Structured agent output validation** — replace regex JSON extraction with schema-validated
   artifacts and a retry-on-invalid loop (Phase 0; the proposal's #22 `schema.json` gestures at
   this without saying it).
4. **Gate-name/stage drift** — fix the confusing state names while decomposing the executor.
5. **The preview runtime is Python/uvicorn-only** (`factory-preview-runtime:1` runs
   `uvicorn app.main:app`). The contract should carry an explicit runtime type so this
   constraint is declared instead of implicit.
6. **Zero dashboard tests** — add a minimal vitest setup when the dashboard gains contract and
   evidence views, so those screens are born tested.

---

## Part 3 — The phased plan

Phases are ordered by dependency, not preference. Each phase states its goal, concrete work
items with file touchpoints, and what "done" means. Phases 1–2 are the heart of the plan;
if only one thing gets built, it should be those.

### Phase 0 — Foundations (enabling work, no behavior change)

**Goal:** make the codebase able to absorb the rest of the plan.

| Item | Work | Touchpoints |
|------|------|-------------|
| 0.1 Executor decomposition | Split `PipelineExecutor` into per-stage modules (`app/pipeline/stages/planning.py`, `implementing.py`, `testing.py`, `build_deploy.py`, `review.py`, `enrichment.py`, `post_production.py`) sharing a `StageContext`. Keep the hardcoded order; introduce a small stage registry so later phases can insert stages (evaluator, adversary) without editing a monolith. Rename gates so `ProjectState` matches what the stage does (fix the `UNIT_TESTING`-runs-integration drift); map old state values on load for existing projects. | `app/pipeline/executor.py`, `app/models.py`, `app/state_machine.py`, all `tests/test_pipeline_*` |
| 0.2 Lightweight migrations | Add a versioned migration runner (a `schema_migrations` table + ordered migration modules; alembic is acceptable but heavier than needed). `init_db` runs `create_all` then pending migrations. | `app/database.py`, new `app/migrations/` |
| 0.3 Structured artifact schemas | Pydantic models for every agent-produced artifact (`review.json`, `enrichment-plan.json`, `work-plan.json`, `repo-exploration.json`, intake forms). One shared `parse_agent_json(schema, text)` helper with a bounded re-ask on invalid output. Delete the scattered regex extractors. | new `app/artifacts/schemas.py`, `agents/*`, `services/product_enrichment.py`, `services/work_planner.py`, `services/repo_exploration.py` |
| 0.4 Prompt externalization + versioning | Move role prompts/rules to files (`app/agents/prompts/<role>/prompt.md`, `rules.md`, `version`). `prompt_builder` becomes a template assembler. Record `{role: prompt_version}` on every task row and agent event. | `agents/prompt_builder.py`, `agents/rules/`, `db_models.TaskRow`, `events` |

**Done when:** all existing orchestrator tests pass; no stage function lives in a file over
~400 lines; a task row shows which prompt versions produced it; an intentionally malformed
agent JSON reply triggers one structured re-ask instead of a silent fallback.

### Phase 1 — Project Contract

**Goal:** the unit of work becomes a structured, human-editable contract with per-requirement
acceptance criteria — the external definition of "good".

| Item | Work | Touchpoints |
|------|------|-------------|
| 1.1 Contract schema | Pydantic model + YAML serialization: `goal`, `users`, `requirements[]` (id, description, acceptance criteria list), `non_goals`, `constraints`, `runtime` (type, healthcheck path/port — supersedes `preview_spec` parsing), `quality_targets`, `security_requirements`. | new `app/contract/` (schema, loader), `services/preview_spec.py` |
| 1.2 Contract generation | The architect's planning output becomes a contract draft (alongside, not replacing, `architecture.md`). Intake answers feed it. Persist to a `project_contracts` table (versioned rows) and write `project.contract.yaml` into the repo so agents and humans see the same source of truth. | `pipeline/stages/planning.py`, `agents/prompts/architect/`, `db_models.py`, migration |
| 1.3 Human contract editing | Dashboard: contract view/edit during `INTAKE_PENDING` and at `REVIEW`. Edits create a new contract version and can trigger a feedback iteration (reuse the existing notes → feedback path). | `dashboard/src/components/`, `api/projects.py`, `services/feedback_pipeline.py` |
| 1.4 Plan coverage gate | Deterministic check in planning: every requirement id maps to ≥1 work unit in `work-plan.json`; unmapped requirements fail planning with a re-plan, before any implementation runs. | `services/work_planner.py` |

**Done when:** a new project produces a structured contract the human can edit; planning
cannot complete with an uncovered requirement; the preview healthcheck comes from the
contract, not the ad-hoc YAML scraper.

### Phase 2 — Evidence graph and acceptance evaluation

**Goal:** replace the file-existence checklist with per-requirement verification backed by
recorded evidence. This is the "Evaluate" step the control loop is missing.

| Item | Work | Touchpoints |
|------|------|-------------|
| 2.1 Evidence tables | `requirements` (from contract, per version) and `evidence` (requirement_id, kind: `test_run` / `commit` / `probe` / `build` / `review` / `screenshot`, reference, pass/fail, payload JSONB, created_at). Migration. | `db_models.py`, `app/migrations/` |
| 2.2 Evidence write paths | Test stages record per-test results mapped to requirement ids (convention: pytest markers / test-name prefixes like `test_r1_*`; the developer prompt mandates the convention). Smoke/staging probes, docker builds, and commits record evidence rows. | `pipeline/stages/testing.py`, `build_deploy.py`, `agents/local_runner.py`, developer prompt |
| 2.3 Acceptance evaluator stage | New stage between smoke testing and review: for each requirement, compute `verified` / `unverified` / `failed` from evidence. Any non-verified requirement fails the gate with a structured report (which feeds the existing fix loop). The reviewer agent now receives the contract + evaluator report + diff stats — its job becomes judging quality and simplicity, not rediscovering whether things exist. Remove the deterministic checklist's ability to override a rejection. | new `pipeline/stages/acceptance.py`, `pipeline/stages/review.py`, reviewer prompt |
| 2.4 Requirement → evidence dashboard | Per-project screen: requirement tree with evidence status and drill-down. Project health % = verified requirements / total, plus test and deployment status — every number clickable through to its evidence. First dashboard tests (vitest) land with this screen. | `dashboard/src/components/`, `lib/api.ts`, `api/projects.py` |

**Done when:** REVIEW can only be reached with every requirement verified or explicitly
waived by the human; the dashboard can answer "why does the factory believe R3 is done?"
with concrete evidence; the old checklist is gone.

### Phase 3 — Persistent engineering memory

**Goal:** institutional memory — agents stop rediscovering the project and repeating failures.

| Item | Work | Touchpoints |
|------|------|-------------|
| 3.1 Memory tables | `architecture_decisions` (decision, alternatives, reason, tradeoffs, agent, date), `failure_records` (gate, stage, error class, summary, attempt count, resolution, project), `known_issues` (description, severity, status: open/fixed/accepted). Migration. | `db_models.py`, `app/migrations/` |
| 3.2 Write paths | `_handle_failure` persists a structured failure record (it already persists `last_failure` to metadata — promote and structure it). Architect output includes a decisions block (schema from 0.3). Tester/adversary findings file known issues. Fixes resolve them. | `pipeline/stages/*`, `agents/prompts/architect/` |
| 3.3 Read path | A bounded "project memory" prompt section: standing decisions, open known issues, and failure records relevant to the current gate (e.g. "staging deploy has failed twice before with X"). Hard character budget so memory can't crowd out the task. | `agents/prompt_builder.py` |
| 3.4 Bug → regression test loop | Policy enforced by the acceptance evaluator: a resolved failure record of class `app` must reference a regression test (`tests/regression/test_<failure_id>.py`) that passes. Fix prompts already say "do not modify tests"; extend them to require the regression test. | `pipeline/stages/acceptance.py`, developer fix prompt |
| 3.5 System map cache | Consolidate `repo_analysis` + `repo_exploration` output into one structured `system-map.json` artifact (components, dependencies, owned files, tests, risk), refreshed after merges. Deterministic Python import-graph feeds `depends_on`. Include relevant `git log` excerpts in existing-repo contexts. | `services/repo_analysis.py`, `services/repo_exploration.py`, `agents/prompt_builder.py` |

**Done when:** a project that failed the same gate twice shows the prior failures in the next
fix prompt; every fixed app bug has a named regression test; decisions survive across
pipeline runs and appear in agent context.

### Phase 4 — Verification depth

**Goal:** someone actually tries to use — and break — the app before a human sees it.

| Item | Work | Touchpoints |
|------|------|-------------|
| 4.1 Agent-backed tester | Allow the tester role to use the Cursor backend (currently hard-excluded via `_CURSOR_ROLES`). Its mandate: generate acceptance tests from the contract into `tests/acceptance/`, run them against the live staging preview, record evidence. Deterministic runner remains the fallback and the floor (health, pytest). Generated repos adopt the taxonomy `tests/{acceptance,integration,regression}/`. | `agents/factory.py`, new tester prompt, `workspace/scaffolder.py` |
| 4.2 Adversarial verifier | New optional stage after smoke, before acceptance evaluation. Independent objective ("disprove that the acceptance criteria are satisfied"), read-only on code, full access to the staging preview (malformed input, restarts via factory API, concurrency, permission probing). Budgeted (time/tokens). Findings become `known_issues` + failing evidence — it fixes nothing. Off by default for the `local` backend; on by default when a Cursor backend is configured. | new `pipeline/stages/adversary.py`, new role + prompt, `models.AgentRole` |
| 4.3 Deployment verification + rollback | On staging deploy and production promote: record the previous image tag, run an observation window (health polls + error-log scan vs. baseline) after cutover, auto-rollback to the previous tag on regression, notify the human. `deployments` rows already carry tags — add `previous_tag` and `verification_status`. | `pipeline/stages/build_deploy.py`, `services/preview_manager.py`, `db_models.DeploymentRow`, migration |
| 4.4 Real diagnosis rung | `DIAGNOSING` runs a bounded deterministic diagnostic (classify infra vs app vs test failure from logs/exit codes, extending `failure_kind`) before a developer fix attempt is spent. Infra failures retry without burning a fix attempt. | `pipeline/stages/` failure handling |
| 4.5 Risk-tiered approvals | Input requests gain a `risk` tier. `destructive` tier (data-loss migration, force-push, secret exposure) has no default-and-timeout — it blocks until the human answers. Everything else keeps the current non-blocking behavior. | `services/input_requests.py`, `db_models.InputRequestRow`, migration, dashboard |

**Done when:** a deliberately planted acceptance-criterion violation (e.g. oversized-upload
accepted) is caught by the adversary or acceptance tests, not the human; a deploy that breaks
`/health` rolls itself back within the observation window; an infra-flavored failure no
longer consumes fix attempts.

### Phase 5 — Measurement and factory self-improvement

**Goal:** improving the factory stops being guesswork.

| Item | Work | Touchpoints |
|------|------|-------------|
| 5.1 Run metrics | `pipeline_runs` table: per run — duration, gates failed, fix attempts per gate, human interventions (input requests answered vs auto-resolved), tokens/cost where the backend reports them, outcome. Dashboard factory-level panel: interventions per successful feature, iterations per feature, regression rate, mean time to successful change. | `db_models.py`, migration, `pipeline/stages/*`, dashboard |
| 5.2 Build manifest | On every successful docker build: write `build-manifest.json` (git commit, agent backend + model, prompt versions from 0.4, contract version, dependency lockfile hash, factory version) as an artifact and attach it to the deployment row. Answers "why did build 183 work and 184 fail". | `pipeline/stages/build_deploy.py` |
| 5.3 Evaluation harness | `benchmarks/` with 3–5 fixture specs (contract + optional seed repo): CRUD API, bug fix in seed repo, feature add to seed repo, broken-deploy recovery, UI feature. A harness script runs the full pipeline per benchmark and scores against each fixture's expected evidence. Two tiers: deterministic `local` backend in CI (pipeline regression), real backend on demand (agent quality scoring, compared across prompt versions). | new `benchmarks/`, `scripts/run_benchmarks.py`, `.github/workflows/` |
| 5.4 Change-size evidence | Per work unit: diff stats (files, lines, new dependencies) recorded as evidence. Over soft thresholds → the agent's required justification is captured and shown to the reviewer. No hard rejection. | `pipeline/stages/implementing.py`, developer prompt, reviewer prompt |

**Done when:** two factory versions (e.g. different prompt versions) can be compared on the
benchmark suite with numbers; every successful build has a manifest; the dashboard shows
intervention and iteration rates per project.

### Phase 6 — Security and infrastructure hardening (deferred, opt-in)

**Goal:** shrink the blast radius of the Docker socket and arbitrary generated code, without
sacrificing one-command install.

| Item | Work |
|------|------|
| 6.1 Socket scoping | Optional docker-socket-proxy sidecar (endpoint-scoped: build, run, inspect, logs — no volume/host mutation endpoints); compose profile so default installs are unchanged. |
| 6.2 Resource + network limits | CPU/memory/pids limits and no-internet network policy on preview containers and builds by default (contract can request internet). |
| 6.3 Container split | Only if operational pain demands it: split supervisord programs (API, worker, dashboard, postgres, redis) into compose services behind the same Caddy gateway, keeping `docker compose up -d` UX. Explicit data-migration path for existing `FACTORY_DATA` installs. Not scheduled; revisit after Phases 1–5. |

---

## Part 4 — Sequencing rationale and risks

**Why this order.** Phase 0 is forced: nothing else lands cleanly in a 2,380-line class with
no migrations. The contract (1) must precede evidence (2), which must precede the adversary
(4) — an adversary without acceptance criteria has nothing to falsify, and an evaluator
without evidence rows has nothing to read. Memory (3) is placed before verification depth (4)
because the adversary and agent tester are *producers* of failure records and known issues;
having the tables ready means their output lands somewhere permanent. Measurement (5) comes
late only because it measures the things built earlier — the run-metrics table itself is cheap
and can be pulled earlier if desired. Infra (6) is deferred deliberately: it improves safety,
not capability, and the socket-proxy quick win inside it doesn't depend on anything else and
can be done whenever convenient.

**What we are explicitly not doing** (and should resist re-adding without new evidence):
optimizer/release agent roles, hard change budgets, a factory-side tool platform, cross-project
organizational memory, Temporal/Prometheus adoption, and the multi-service container split.

**Risks to watch:**

- *Pipeline latency and cost creep.* Each new stage (evaluator, adversary, observation window)
  adds wall-clock time and tokens. Mitigations: adversary is budgeted and skippable per
  project; evaluator is deterministic (reads evidence rows, no LLM required); observation
  windows are minutes, not hours.
- *Contract quality ceiling.* If architect-generated acceptance criteria are vague, the whole
  evidence chain inherits the vagueness. Mitigations: human editing at intake (1.3), the plan
  coverage gate (1.4), and benchmark fixtures with hand-written contracts (5.3) to measure
  criteria quality.
- *Evidence-mapping friction.* Requirement-to-test mapping via naming conventions can be
  gamed or forgotten by agents. The acceptance evaluator treats unmapped requirements as
  `unverified` (fail-closed), which makes gaming unprofitable.
- *State-rename migration.* 0.1's gate renames touch persisted `projects.state` values and
  dashboard constants. Ship with a value-mapping on read and a one-time migration; test
  resume-from-every-state (tests for resume already exist to extend).
- *Existing installs.* Every migration must be additive or mapped; `FACTORY_DATA` volumes in
  the wild must survive upgrades. The migration runner (0.2) exists precisely so this is
  checked, not hoped.
