"""Run project live previews in ephemeral Docker containers on an isolated network."""

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

_DEFAULT_DOCKERFILE = """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
"""

_PREVIEW_LABELS = (
    "factory.preview=1",
)


def preview_container_name(project_id: UUID) -> str:
    return f"factory-live-{str(project_id)[:8]}"


def dev_preview_image_tag(project_id: UUID) -> str:
    return f"factory-preview-dev-{str(project_id)[:8]}"


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


async def _run_docker(*args: str, stdin: bytes | None = None, log_path: Path | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate(input=stdin)
    output = stdout.decode(errors="replace")
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(output)
            if not output.endswith("\n"):
                handle.write("\n")
    return proc.returncode or 0, output


async def _remove_container(name: str) -> None:
    await _run_docker("rm", "-f", name)


async def _remove_image(image_ref: str) -> None:
    if not image_ref:
        return
    await _run_docker("rmi", "-f", image_ref)


async def stop_preview(
    project_id: UUID,
    *,
    container_name: str | None = None,
    ephemeral_image: str | None = None,
) -> None:
    """Stop preview container and remove ephemeral preview images (never volumes)."""
    name = container_name or preview_container_name(project_id)
    await _remove_container(name)

    for image in {ephemeral_image, dev_preview_image_tag(project_id)}:
        if image:
            await _remove_image(image)


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
    code, output = await _run_docker("inspect", "-f", field, container_ref)
    if code != 0:
        return None
    value = output.strip()
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
    if backend not in ("docker", "subprocess"):
        return None

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


def _build_label_args(project_id: UUID, *, ephemeral: bool = False) -> list[str]:
    args = ["--label", "factory.preview=1", "--label", f"factory.project={project_id}"]
    if ephemeral:
        args.extend(["--label", "factory.preview.ephemeral=1"])
    return args


async def _build_ephemeral_image(
    project_id: UUID,
    repo_path: Path,
    image_tag: str,
    log_path: Path,
) -> tuple[bool, str]:
    repo_path = repo_path.resolve()
    dockerfile = repo_path / "Dockerfile"
    context = str(repo_path)
    label_args = _build_label_args(project_id, ephemeral=True)

    # Use project Dockerfile only when present and non-empty; always pass absolute context.
    if dockerfile.is_file() and dockerfile.stat().st_size > 0:
        code, output = await _run_docker(
            "build",
            "-t",
            image_tag,
            "-f",
            str(dockerfile),
            *label_args,
            context,
            log_path=log_path,
        )
    else:
        code, output = await _run_docker(
            "build",
            "-t",
            image_tag,
            "-f",
            "-",
            *label_args,
            context,
            stdin=_DEFAULT_DOCKERFILE.encode(),
            log_path=log_path,
        )

    if code != 0:
        await _remove_image(image_tag)
        tail = "\n".join(output.splitlines()[-20:])
        return False, f"Docker build failed:\n{tail}"
    return True, f"Built ephemeral preview image {image_tag}"


async def _run_preview_container(
    project_id: UUID,
    image_tag: str,
    *,
    env_vars: dict[str, str] | None = None,
    ephemeral: bool = False,
) -> tuple[bool, str, str | None]:
    ensure_preview_network()
    name = preview_container_name(project_id)
    await _remove_container(name)

    cmd = [
        "run",
        "-d",
        "--name",
        name,
        "--network",
        settings.preview_docker_network,
        *_build_label_args(project_id, ephemeral=ephemeral),
    ]
    for key, value in (env_vars or {}).items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.append(image_tag)

    code, output = await _run_docker(*cmd)
    if code != 0:
        return False, output or "docker run failed", None

    container_id = output.strip()[:12] if output.strip() else None
    health_url = f"http://{name}:8080/health"
    if not await _wait_for_health(health_url, attempts=45):
        await _remove_container(name)
        return False, f"Container preview failed health check at {health_url}", container_id

    return True, f"Preview container {name} on {settings.preview_docker_network}", container_id


async def start_dev_preview(
    project_id: UUID,
    repo_path: Path,
    log_path: Path,
    *,
    env_vars: dict[str, str] | None = None,
) -> tuple[bool, str, str | None, str | None]:
    """Build a throwaway image from the repo and run it in an isolated container."""
    if not Path("/var/run/docker.sock").exists():
        return False, "Docker is not available for preview", None, None

    main_module = repo_path / "app" / "main.py"
    if not main_module.exists():
        return False, f"Preview aborted — missing {main_module.relative_to(repo_path)}", None, None

    image_tag = dev_preview_image_tag(project_id)
    await stop_preview(project_id, ephemeral_image=image_tag)

    built, build_msg = await _build_ephemeral_image(project_id, repo_path, image_tag, log_path)
    if not built:
        return False, build_msg, None, None

    success, output, container_id = await _run_preview_container(
        project_id,
        image_tag,
        env_vars=env_vars,
        ephemeral=True,
    )
    if not success:
        await _remove_image(image_tag)
        return False, output, container_id, None

    message = f"{build_msg}; {output}"
    return True, message, container_id, image_tag


async def start_docker_preview(
    project_id: UUID,
    image_tag: str,
    *,
    env_vars: dict[str, str] | None = None,
) -> tuple[bool, str, str | None]:
    """Run a built project image on the preview Docker network (container only, keeps image)."""
    await stop_preview(project_id, container_name=preview_container_name(project_id))
    return await _run_preview_container(project_id, image_tag, env_vars=env_vars, ephemeral=False)


async def cleanup_orphan_preview_resources() -> dict[str, int]:
    """Remove leftover preview containers and ephemeral preview images."""
    if not Path("/var/run/docker.sock").exists():
        return {"containers": 0, "images": 0}

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
    container_ids = [line.strip() for line in stdout.decode().splitlines() if line.strip()]
    for cid in container_ids:
        await _remove_container(cid)

    proc = await asyncio.create_subprocess_exec(
        "docker",
        "images",
        "-q",
        "--filter",
        "label=factory.preview.ephemeral=1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    image_ids = [line.strip() for line in stdout.decode().splitlines() if line.strip()]
    for iid in image_ids:
        await _run_docker("rmi", "-f", iid)

    return {"containers": len(container_ids), "images": len(image_ids)}


# Backwards-compatible alias
async def cleanup_orphan_preview_containers() -> int:
    result = await cleanup_orphan_preview_resources()
    return result["containers"]
