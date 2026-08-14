"""Run project live previews inside the factory container or on an isolated Docker network."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from uuid import UUID

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# project_id -> asyncio subprocess handle
_dev_processes: dict[str, asyncio.subprocess.Process] = {}


def preview_container_name(project_id: UUID) -> str:
    return f"factory-live-{str(project_id)[:8]}"


def ensure_preview_network() -> None:
    """Create the shared preview network and attach this factory container."""
    if not Path("/var/run/docker.sock").exists():
        return
    network = settings.preview_docker_network
    subprocess.run(
        ["docker", "network", "create", network],
        capture_output=True,
        check=False,
    )
    cid = os.environ.get("HOSTNAME", "").strip()
    if cid:
        subprocess.run(
            ["docker", "network", "connect", network, cid],
            capture_output=True,
            check=False,
        )


async def _remove_container(name: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "rm",
        "-f",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def stop_preview(project_id: UUID, *, container_name: str | None = None) -> None:
    """Stop dev subprocess and/or Docker preview for a project."""
    key = str(project_id)
    proc = _dev_processes.pop(key, None)
    if proc and proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    name = container_name or preview_container_name(project_id)
    await _remove_container(name)


async def _wait_for_health(url: str, *, attempts: int = 30, delay: float = 1.0) -> bool:
    async with httpx.AsyncClient(timeout=5.0) as client:
        for _ in range(attempts):
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(delay)
    return False


async def _docker_inspect(field: str, container_ref: str) -> str | None:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "inspect",
        "-f",
        field,
        container_ref,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    value = stdout.decode().strip()
    return value or None


async def container_is_running(container_ref: str) -> bool:
    state = await _docker_inspect("{{.State.Running}}", container_ref)
    return state == "true"


async def container_ip_on_network(container_ref: str, network: str) -> str | None:
    field = f"{{{{(index .NetworkSettings.Networks \"{network}\").IPAddress}}}}"
    ip = await _docker_inspect(field, container_ref)
    if ip and ip != "<no value>":
        return ip
    return None


async def resolve_preview_upstream(project_id: UUID, meta: dict) -> str | None:
    """Resolve a reachable internal URL for the project preview proxy."""
    backend = meta.get("preview_backend")
    if backend == "docker":
        ensure_preview_network()
        name = meta.get("preview_container")
        if not name or len(str(name)) <= 12:
            name = preview_container_name(project_id)
        if not await container_is_running(name):
            logger.warning("Preview container %s is not running for project %s", name, project_id)
            return None
        ip = await container_ip_on_network(name, settings.preview_docker_network)
        host = ip or name
        return f"http://{host}:8080"

    port = meta.get("preview_internal_port") or meta.get("preview_port") or meta.get("staging_port")
    if port:
        key = str(project_id)
        proc = _dev_processes.get(key)
        if proc is not None and proc.returncode is not None:
            logger.warning("Dev preview process exited for project %s", project_id)
            return None
        health_url = f"http://127.0.0.1:{port}/health"
        if not await _wait_for_health(health_url, attempts=1, delay=0):
            logger.warning("Dev preview on port %s is not healthy for project %s", port, project_id)
            return None
        return f"http://127.0.0.1:{port}"
    return None


async def start_dev_preview(
    project_id: UUID,
    repo_path: Path,
    port: int,
    log_path: Path,
) -> tuple[bool, str, str | None]:
    """Run uvicorn from the project repo on an internal port (no host publish)."""
    await stop_preview(project_id)

    req = repo_path / "requirements.txt"
    if req.exists():
        install = await asyncio.create_subprocess_exec(
            "pip",
            "install",
            "-q",
            "-r",
            str(req),
            "uvicorn",
            cwd=str(repo_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT,
        )
        await install.wait()

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "a", encoding="utf-8")
    proc = await asyncio.create_subprocess_exec(
        "python3",
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        cwd=str(repo_path),
        env={**os.environ, "PYTHONPATH": str(repo_path)},
        stdout=log_handle,
        stderr=asyncio.subprocess.STDOUT,
    )
    _dev_processes[str(project_id)] = proc

    health_url = f"http://127.0.0.1:{port}/health"
    if not await _wait_for_health(health_url, attempts=45):
        await stop_preview(project_id)
        return False, f"Dev preview failed to become healthy at {health_url}", None

    return True, f"Dev preview on internal port {port}", str(proc.pid)


async def start_docker_preview(
    project_id: UUID,
    image_tag: str,
    *,
    env_vars: dict[str, str] | None = None,
) -> tuple[bool, str, str | None]:
    """Run a built image on the preview Docker network (no host port mapping)."""
    ensure_preview_network()
    name = preview_container_name(project_id)
    await stop_preview(project_id, container_name=name)

    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        settings.preview_docker_network,
        "--label",
        "factory.preview=1",
        "--label",
        f"factory.project={project_id}",
    ]
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
    if proc.returncode != 0:
        return False, output or "docker run failed", None

    container_id = output[:12] if output else None
    health_url = f"http://{name}:8080/health"
    if not await _wait_for_health(health_url, attempts=45):
        await stop_preview(project_id, container_name=name)
        return False, f"Container preview failed health check at {health_url}", container_id

    return True, f"Docker preview container {name} on {settings.preview_docker_network}", container_id


async def cleanup_orphan_preview_containers() -> int:
    """Remove leftover preview containers from previous runs."""
    if not Path("/var/run/docker.sock").exists():
        return 0
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "ps",
        "-aq",
        "--filter",
        "label=factory.preview=1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    ids = [line.strip() for line in stdout.decode().splitlines() if line.strip()]
    for cid in ids:
        await _remove_container(cid)
    return len(ids)
