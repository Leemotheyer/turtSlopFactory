import asyncio
import json
import os
import subprocess
from uuid import UUID

import httpx

from app.agents.base import AgentRun, AgentRunner
from app.models import AgentRole
from app.workspace.manager import WorkspaceManager
from app.workspace.scaffolder import (
    apply_incremental_fix,
    scaffold_backend,
    scaffold_base,
    scaffold_feature,
    scaffold_frontend,
    scaffold_web_app,
)


from app.services.env_detection import detect_env_keys_from_text


class LocalAgentRunner(AgentRunner):
    """Deterministic agent that scaffolds, tests, and reviews without external LLM APIs."""

    def __init__(self, workspace: WorkspaceManager | None = None) -> None:
        self.workspace = workspace or WorkspaceManager()

    async def _detect_env_requirements(self, project_id: UUID, description: str, context: dict) -> None:
        request_env = context.get("request_env_var")
        if not request_env:
            return

        configured = set(context.get("env_status", {}).get("configured_keys", []))
        text = description or ""
        for note in context.get("notes", []):
            text += " " + note.get("content", "")

        requested: set[str] = set()
        for key_name, desc in detect_env_keys_from_text(text):
            if key_name not in configured and key_name not in requested:
                await request_env(key_name, desc, requested_by="developer")
                requested.add(key_name)
                self.workspace.append_log(
                    project_id,
                    "pipeline.log",
                    f"[developer] Requested secret {key_name} (value hidden from agents)",
                )

    async def run(
        self,
        role: AgentRole,
        project_id: UUID,
        task_id: UUID,
        workspace: str,
        context: dict,
    ) -> AgentRun:
        agent_id = f"{role.value}-{str(task_id)[:8]}"
        run = AgentRun(task_id=task_id, role=role, agent_id=agent_id)
        name = context.get("name", "app")
        description = context.get("description", "")

        if role == AgentRole.ARCHITECT:
            if context.get("repo_exploration"):
                run.output = await self._architect_repo_exploration(project_id, context)
            elif context.get("enrichment_pass"):
                run.output = await self._architect_enrichment(project_id, context)
            else:
                run.output = await self._architect(project_id, name, description, context)
            run.success = True
        elif role == AgentRole.DEVELOPER:
            stream = context.get("work_stream")
            if stream:
                run.output = await self._developer_stream(
                    project_id, name, description, context, stream, task_id, agent_id
                )
            else:
                run.output = await self._developer(
                    project_id, name, description, context, task_id, agent_id
                )
            run.success = True
        elif role == AgentRole.TESTER:
            run.success, run.output = await self._tester(project_id, context)
        elif role == AgentRole.REVIEWER:
            run.success, run.output = await self._reviewer(project_id, context, task_id, agent_id)
        else:
            run.output = f"Unknown role: {role}"
            run.success = False

        return run

    async def stream_events(self, run_id: UUID):
        return
        yield  # pragma: no cover

    def _format_notes_section(self, notes: list[dict]) -> str:
        if not notes:
            return ""
        lines = ["\n## Supervisor notes (must follow)"]
        for n in notes:
            label = n.get("type", "note").replace("_", " ").title()
            lines.append(f"- **[{label}]** {n.get('content', '')}")
        return "\n".join(lines) + "\n"

    async def _architect_repo_exploration(self, project_id: UUID, context: dict) -> str:
        from app.services.repo_exploration import explore_repo_locally, normalize_exploration_payload

        repo = self.workspace.repo_dir(project_id)
        local = explore_repo_locally(repo, context.get("description") or "")
        payload = normalize_exploration_payload(local, method="local_heuristic")
        text = json.dumps(payload, indent=2)
        self.workspace.write_artifact(project_id, "repo-exploration.json", text)
        self.workspace.append_log(
            project_id,
            "pipeline.log",
            "[architect] Local heuristic repo exploration (no Cursor API for deep read)",
        )
        return text

    async def _architect(self, project_id: UUID, name: str, description: str, context: dict) -> str:
        notes_section = self._format_notes_section(context.get("notes", []))
        scope_out = [n for n in context.get("notes", []) if n.get("type") == "scope_out"]
        excluded = "\n".join(f"- OUT OF SCOPE: {n['content']}" for n in scope_out) if scope_out else ""

        intake = context.get("intake", {})
        intake_section = ""
        if intake:
            intake_section = "\n## Intake form answers\n"
            for key, val in intake.items():
                if isinstance(val, list):
                    val = ", ".join(val)
                intake_section += f"- **{key.replace('_', ' ').title()}:** {val}\n"

        loose_plan = context.get("loose_plan", "")
        plan_ref = f"\n## Discovery plan\nSee discovery-plan.md artifact.\n" if loose_plan else ""

        requirements = f"""# Requirements: {name}

## Overview
{description}
{notes_section}{intake_section}{plan_ref}
## Functional requirements
1. Expose a `/health` endpoint returning JSON status
2. Provide a REST API for item management (create, list, get)
3. Serve a web UI for browser interaction
4. Run in Docker with healthcheck support

## Exclusions
{excluded or "None specified"}

## Non-functional requirements
- Python 3.12 + FastAPI
- Unit and integration test coverage
- Containerized deployment on port 8080
"""
        architecture = f"""# Architecture: {name}

## Stack
- **Backend:** FastAPI
- **Frontend:** Static HTML/JS served by FastAPI
- **Storage:** In-memory (demo); swap for PostgreSQL in production
- **Deployment:** Docker + docker-compose

## API
| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| GET | /api/info | Service metadata |
| GET | /api/items | List items |
| POST | /api/items | Create item |
| GET | /api/items/{{id}} | Get item |

## Testing strategy
- Unit tests via pytest + TestClient
- Integration tests for full API workflow
- Container smoke test on /health
"""
        self.workspace.write_artifact(project_id, "requirements.md", requirements)
        self.workspace.write_artifact(project_id, "architecture.md", architecture)
        self.workspace.append_log(project_id, "pipeline.log", f"[architect] Planned {name}")
        return f"Created requirements.md and architecture.md for {name}"

    async def _architect_enrichment(self, project_id: UUID, context: dict) -> str:
        from app.services.product_enrichment import local_enrichment_plan

        audit = context.get("preview_audit") or {}
        pass_number = int(context.get("enrichment_pass") or 1)
        completed = set(context.get("enrichment_completed") or [])
        plan = local_enrichment_plan(
            audit,
            pass_number,
            context.get("notes", []),
            max_passes=context.get("max_enrichment_passes"),
            completed_slugs=completed,
        )
        payload = json.dumps(plan, indent=2)
        self.workspace.write_artifact(project_id, "enrichment-plan.json", payload)
        self.workspace.append_log(
            project_id,
            "pipeline.log",
            f"[architect] Enrichment pass {pass_number}: {len(plan.get('features') or [])} feature(s)",
        )
        return payload

    def _format_input_section(self, responses: list[dict]) -> str:
        if not responses:
            return ""
        lines = ["\n## Supervisor decisions (apply these)"]
        for r in responses:
            decision = r.get("resolved_decision") or r.get("default_decision", "")
            lines.append(f"- Q: {r.get('question', '')}")
            lines.append(f"  A: {decision}")
        return "\n".join(lines) + "\n"

    async def _developer_stream(
        self,
        project_id: UUID,
        name: str,
        description: str,
        context: dict,
        stream: str,
        task_id: UUID,
        agent_id: str,
    ) -> str:
        repo = self.workspace.repo_dir(project_id)
        incremental = context.get("incremental", False)

        lock = context.setdefault("_scaffold_lock", asyncio.Lock())
        async with lock:
            if not incremental and not (repo / "requirements.txt").exists():
                scaffold_base(repo, name, description)

        input_section = self._format_input_section(context.get("input_responses", []))
        if input_section:
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[{stream}] Applying {len(context.get('input_responses', []))} supervisor decisions",
            )

        if stream == "backend":
            if context.get("fix_attempt", 0) > 0 and context.get("last_failure"):
                apply_incremental_fix(repo, context["last_failure"])
            files = scaffold_backend(repo, name, description + input_section)
            label = "backend API"
        elif stream == "frontend":
            files = scaffold_frontend(repo, name, description)
            label = "frontend UI"
        elif stream == "feature":
            feature_id = context.get("feature_id") or "feature"
            content = context.get("feature_content") or context.get("work_description", "")
            files = scaffold_feature(repo, feature_id, content)
            label = f"feature {feature_id}"
        else:
            return f"Unknown work stream: {stream}"

        self.workspace.append_log(
            project_id,
            "pipeline.log",
            f"[{stream}] Wrote {len(files)} files ({label})",
        )
        return f"[{stream}] Updated {len(files)} files"

    async def _developer(
        self,
        project_id: UUID,
        name: str,
        description: str,
        context: dict,
        task_id: UUID,
        agent_id: str,
    ) -> str:
        notes = context.get("notes", [])
        for note in notes:
            if note.get("type") == "feature":
                self.workspace.append_log(
                    project_id,
                    "pipeline.log",
                    f"[developer] Noted feature request: {note['content'][:80]}",
                )

        await self._detect_env_requirements(project_id, description, context)

        incremental = context.get("incremental", False)
        repo = self.workspace.repo_dir(project_id)
        if incremental or (repo / "app" / "main.py").exists():
            if context.get("fix_attempt", 0) > 0 and context.get("last_failure"):
                apply_incremental_fix(repo, context["last_failure"])
            files = []
            files.extend(scaffold_backend(repo, name, description))
            files.extend(scaffold_frontend(repo, name, description))
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[developer] Incremental update ({len(files)} files)",
            )
            return f"Incremental update applied ({len(files)} files, {len(notes)} notes)"

        request_input = context.get("request_input")
        if request_input:
            default = "Use in-memory storage for v1; defer PostgreSQL to a follow-up task"
            await request_input(
                agent_id=agent_id,
                role="developer",
                question="Should this app use persistent database storage or in-memory for v1?",
                context_detail="Affects schema design and Docker compose services.",
                options=["In-memory (faster v1)", "PostgreSQL (production-ready)", "SQLite (middle ground)"],
                default_decision=default,
                task_id=task_id,
            )
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[developer] Proceeded with default: {default}",
            )

        input_responses = context.get("input_responses", [])
        for resp in input_responses:
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[developer] Supervisor decision: {resp.get('resolved_decision', '')[:80]}",
            )

        repo = self.workspace.reset_repo(project_id)
        files = scaffold_web_app(repo, name, description)
        self.workspace.append_log(
            project_id, "pipeline.log", f"[developer] Scaffolded {len(files)} files"
        )
        return f"Scaffolded application with {len(files)} files (applied {len(notes)} supervisor notes)"

    async def _tester(self, project_id: UUID, context: dict) -> tuple[bool, str]:
        stage = context.get("test_stage", "unit")
        repo = self.workspace.repo_dir(project_id)

        if stage == "unit":
            return await self._run_pytest(repo, project_id, "tests/test_app.py")
        if stage == "integration":
            return await self._run_pytest(repo, project_id, "tests/")
        if stage == "smoke":
            return await self._run_smoke(project_id, context)
        if stage == "product_qa":
            return await self._run_product_qa(project_id, context)
        if stage == "mobile_check":
            return await self._run_mobile_check(project_id, context)
        return False, f"Unknown test stage: {stage}"

    async def _run_pytest(self, repo, project_id: UUID, target: str) -> tuple[bool, str]:
        self.workspace.append_log(project_id, "pipeline.log", f"[tester] Running pytest {target}")

        # Install project dependencies first
        req = repo / "requirements.txt"
        if req.exists():
            install = await asyncio.create_subprocess_exec(
                "pip",
                "install",
                "-q",
                "-r",
                str(req),
                "pytest",
                cwd=str(repo),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await install.communicate()

        proc = await asyncio.create_subprocess_exec(
            "python3",
            "-m",
            "pytest",
            target,
            "-v",
            "--tb=short",
            cwd=str(repo),
            env={**os.environ, "PYTHONPATH": str(repo)},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        self.workspace.write_log(project_id, f"pytest-{target.replace('/', '-')}.log", output)
        success = proc.returncode == 0
        self.workspace.append_log(
            project_id,
            "pipeline.log",
            f"[tester] pytest {'PASSED' if success else 'FAILED'} (exit {proc.returncode})",
        )
        return success, output

    async def _run_smoke(self, project_id: UUID, context: dict) -> tuple[bool, str]:
        upstream = context.get("preview_upstream")
        health_path = context.get("preview_health_path") or "/health"
        if not str(health_path).startswith("/"):
            health_path = f"/{health_path}"
        if upstream:
            url = f"{upstream.rstrip('/')}{health_path}"
        else:
            port = context.get("preview_app_port") or context.get("staging_port")
            if not port:
                return False, "No factory live preview is running"
            url = f"http://127.0.0.1:{port}{health_path}"

        self.workspace.append_log(project_id, "pipeline.log", f"[tester] Smoke test {url}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for _ in range(15):
                    try:
                        r = await client.get(url)
                        if 200 <= r.status_code < 300:
                            body = ""
                            try:
                                body = r.json()
                            except Exception:
                                body = r.text[:200]
                            if isinstance(body, dict) and body.get("status") not in (None, "ok", "healthy", "ready"):
                                return False, f"Health check returned unexpected payload: {body}"
                            return True, f"Smoke test passed: {body}"
                    except httpx.HTTPError:
                        await asyncio.sleep(1)
                return False, f"Health check failed at {url}"
        except Exception as exc:
            return False, str(exc)

    async def _run_product_qa(self, project_id: UUID, context: dict) -> tuple[bool, str]:
        from app.services.product_enrichment import audit_live_preview

        audit = context.get("preview_audit") or await audit_live_preview(context)
        issues = list(audit.get("issues") or [])
        suggested: list[str] = []

        if not audit.get("health_ok"):
            issues.append("Health endpoint is not healthy")
        if not audit.get("has_html_ui"):
            suggested.append("Add or fix the HTML UI served at /")
        if audit.get("has_html_ui") and not audit.get("mobile_friendly"):
            issues.append("UI lacks mobile-friendly signals (viewport meta / responsive CSS)")

        for endpoint in audit.get("endpoints") or []:
            if endpoint.get("path") == "/api/items" and endpoint.get("ok"):
                suggested.append("Verify create/update/delete flows in the UI")
                break
        else:
            suggested.append("Implement working /api/items endpoints")

        passed = audit.get("health_ok") and (audit.get("has_html_ui") or context.get("repo_url"))
        report = {
            "passed": passed,
            "issues": issues,
            "suggested_features": suggested,
        }
        payload = json.dumps(report, indent=2)
        self.workspace.write_artifact(project_id, "product-qa.json", payload)
        self.workspace.append_log(
            project_id,
            "pipeline.log",
            f"[tester] Product QA {'passed' if passed else 'found issues'} ({len(issues)} issue(s))",
        )
        summary = f"Product QA: {'PASS' if passed else 'ISSUES'} — {', '.join(issues[:3]) or 'ok'}"
        return passed, summary

    async def _run_mobile_check(self, project_id: UUID, context: dict) -> tuple[bool, str]:
        from app.services.product_enrichment import audit_live_preview

        audit = context.get("preview_audit") or await audit_live_preview(context)
        issues: list[str] = []
        if not audit.get("has_html_ui"):
            issues.append("No HTML UI to evaluate")
        elif not audit.get("viewport_meta"):
            issues.append("Missing viewport meta tag")
        if audit.get("has_html_ui") and not audit.get("responsive_signals"):
            issues.append("No responsive CSS signals detected")

        passed = audit.get("mobile_friendly", False) and audit.get("has_html_ui", False)
        report = {
            "passed": passed,
            "viewport_meta": audit.get("viewport_meta"),
            "responsive_signals": audit.get("responsive_signals") or [],
            "issues": issues,
        }
        payload = json.dumps(report, indent=2)
        self.workspace.write_artifact(project_id, "mobile-check.json", payload)
        summary = f"Mobile check: {'PASS' if passed else 'ISSUES'} — {', '.join(issues[:3]) or 'ok'}"
        return passed, summary

    async def _reviewer(
        self, project_id: UUID, context: dict, task_id: UUID, agent_id: str
    ) -> tuple[bool, str]:
        artifacts = self.workspace.list_artifacts(project_id)
        has_req = "requirements.md" in artifacts
        has_arch = "architecture.md" in artifacts
        tests_passed = context.get("tests_passed", False)

        request_input = context.get("request_input")
        rate_limit_default = "Skip rate limiting for v1; add before public production launch"
        if request_input:
            await request_input(
                agent_id=agent_id,
                role="reviewer",
                question="Should rate limiting be required before approving this build?",
                context_detail="No rate limiting middleware is currently implemented.",
                options=["Require before approve", "Defer to v2", "Add basic IP rate limit now"],
                default_decision=rate_limit_default,
                task_id=task_id,
            )
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[reviewer] Proceeded with default: {rate_limit_default}",
            )

        notes_applied = len([n for n in context.get("notes", []) if n.get("type") != "scope_out"])
        checklist = {
            "requirements_documented": has_req,
            "architecture_documented": has_arch,
            "all_tests_passed": tests_passed,
            "dockerfile_present": (self.workspace.repo_dir(project_id) / "Dockerfile").exists(),
            "supervisor_notes_applied": notes_applied == 0 or has_req,
        }
        approved = all(checklist.values())
        concerns = [k for k, v in checklist.items() if not v]

        report = {
            "decision": "approve" if approved else "reject",
            "checklist": checklist,
            "concerns": concerns,
            "severity": "low" if approved else "high",
        }
        import json

        self.workspace.write_artifact(project_id, "review.json", json.dumps(report, indent=2))
        self.workspace.append_log(
            project_id,
            "pipeline.log",
            f"[reviewer] {'APPROVED' if approved else 'REJECTED'}: {checklist}",
        )
        return approved, json.dumps(report, indent=2)

    async def docker_build(self, project_id: UUID, tag: str) -> tuple[bool, str]:
        from app.workspace.scaffolder import ensure_dockerfile

        repo = self.workspace.repo_dir(project_id)
        ensure_dockerfile(repo)
        self.workspace.append_log(project_id, "pipeline.log", f"[build] docker build -t {tag}")

        proc = await asyncio.create_subprocess_exec(
            "docker",
            "build",
            "-t",
            tag,
            ".",
            cwd=str(repo),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        self.workspace.write_log(project_id, "docker-build.log", output)
        return proc.returncode == 0, output

    def docker_available(self) -> bool:
        try:
            subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=5)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
