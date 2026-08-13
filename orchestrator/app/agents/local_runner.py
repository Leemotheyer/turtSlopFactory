import asyncio
import os
import re
import subprocess
from uuid import UUID

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


_ENV_KEY_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bopenai\b", re.I), "OPENAI_API_KEY", "OpenAI API key for LLM features"),
    (re.compile(r"\banthropic\b|\bclaude\b", re.I), "ANTHROPIC_API_KEY", "Anthropic API key"),
    (re.compile(r"\bstripe\b", re.I), "STRIPE_SECRET_KEY", "Stripe secret key for payments"),
    (re.compile(r"\bsendgrid\b", re.I), "SENDGRID_API_KEY", "SendGrid API key for email"),
    (re.compile(r"\btwilio\b", re.I), "TWILIO_AUTH_TOKEN", "Twilio auth token for SMS/voice"),
    (re.compile(r"\baws\b|\bs3\b", re.I), "AWS_SECRET_ACCESS_KEY", "AWS secret access key"),
    (re.compile(r"\bgithub\b.*\btoken\b|\bgh[_\s]?token\b", re.I), "GITHUB_TOKEN", "GitHub personal access token"),
    (re.compile(r"\bapi[_\s]?key\b", re.I), "API_KEY", "Generic API key referenced in project spec"),
]


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
        for pattern, key_name, desc in _ENV_KEY_PATTERNS:
            if pattern.search(text) and key_name not in configured and key_name not in requested:
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
        port = context.get("staging_port")
        if not port:
            return False, "No staging port configured"

        import httpx

        url = f"http://127.0.0.1:{port}/health"
        self.workspace.append_log(project_id, "pipeline.log", f"[tester] Smoke test {url}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for _ in range(10):
                    try:
                        r = await client.get(url)
                        if r.status_code == 200 and r.json().get("status") == "ok":
                            return True, f"Smoke test passed: {r.json()}"
                    except httpx.HTTPError:
                        await asyncio.sleep(1)
                return False, f"Health check failed at {url}"
        except Exception as exc:
            return False, str(exc)

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
        repo = self.workspace.repo_dir(project_id)
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

    def _live_container_name(self, project_id: UUID) -> str:
        return f"factory-live-{str(project_id)[:8]}"

    async def _remove_container(self, container_name: str) -> None:
        await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def deploy_dev_preview(
        self,
        project_id: UUID,
        port: int,
        repo_path,
        env_vars: dict[str, str] | None = None,
    ) -> tuple[bool, str, str | None]:
        """Run the app from source in Docker so the user can preview while tests iterate."""
        container_name = self._live_container_name(project_id)
        await self._remove_container(container_name)

        env_flags: list[str] = []
        for key, value in (env_vars or {}).items():
            env_flags.extend(["-e", f"{key}={value}"])

        startup = (
            "pip install -q -r requirements.txt && "
            "uvicorn app.main:app --host 0.0.0.0 --port 8080"
        )
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-p",
            f"{port}:8080",
            "-v",
            f"{repo_path}:/app",
            "-w",
            "/app",
            *env_flags,
            "python:3.12-slim",
            "bash",
            "-c",
            startup,
        ]

        self.workspace.append_log(
            project_id,
            "pipeline.log",
            f"[preview] dev container on :{port} from {repo_path}",
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode().strip()
        container_id = output[:12] if proc.returncode == 0 else None
        return proc.returncode == 0, output, container_id

    async def deploy_staging(
        self,
        project_id: UUID,
        image_tag: str,
        port: int,
        env_vars: dict[str, str] | None = None,
    ) -> tuple[bool, str, str | None]:
        """Replace the live preview container with a built Docker image."""
        container_name = self._live_container_name(project_id)
        await self._remove_container(container_name)

        cmd = ["docker", "run", "-d", "--name", container_name, "-p", f"{port}:8080"]
        for key, value in (env_vars or {}).items():
            cmd.extend(["-e", f"{key}={value}"])
        cmd.append(image_tag)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode().strip()
        container_id = output[:12] if proc.returncode == 0 else None
        self.workspace.append_log(
            project_id, "pipeline.log", f"[preview] docker image on :{port} -> {container_id}"
        )
        return proc.returncode == 0, output, container_id

    async def stop_live_preview(self, project_id: UUID) -> None:
        await self._remove_container(self._live_container_name(project_id))
