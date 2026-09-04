"""Factory-owned live previews: isolated containers agents never have to start."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from uuid import UUID

import httpx

from app.config import settings
from app.services.preview_spec import (
    DEFAULT_HEALTH_PATH,
    DEFAULT_PREVIEW_PORT,
    PIP_CACHE_VOLUME,
    PREVIEW_RUNTIME_IMAGE,
    PreviewHealthSpec,
    PreviewLaunch,
    detect_app_module,
    gateway_preview_prefix,
    load_preview_spec,
    runtime_start_command,
)

logger = logging.getLogger(__name__)

_RUNTIME_DOCKERFILE = """FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic httpx
"""

_FALLBACK_RUNTIME_IMAGE = "python:3.12-slim"


def preview_container_name(project_id: UUID) -> str:
    return f"factory-live-{str(project_id)[:8]}"


def dev_preview_image_tag(project_id: UUID) -> str:
    """Legacy project-specific preview image tag (cleaned up if still present)."""
    return f"factory-preview-dev-{str(project_id)[:8]}"


def docker_available() -> bool:
    if settings.disable_docker:
        return False
    # Hardened deploys reach Docker through a socket proxy (DOCKER_HOST)
    # instead of a mounted socket file.
    if os.environ.get("DOCKER_HOST"):
        return True
    return Path("/var/run/docker.sock").exists()


def ensure_preview_network() -> None:
    """Create the shared preview network and attach this factory container."""
    if not docker_available():
        return
    network = settings.preview_docker_network
    subprocess_run_silent(["docker", "network", "create", network])
    cid = os.environ.get("HOSTNAME", "").strip()
    if cid:
        subprocess_run_silent(["docker", "network", "connect", network, cid])


def subprocess_run_silent(cmd: list[str]) -> None:
    import subprocess

    subprocess.run(cmd, capture_output=True, check=False)


async def _run_docker(*args: str, stdin: bytes | None = None, log_path: Path | None = None) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return 127, "docker binary not available"
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
    if image_ref in {PREVIEW_RUNTIME_IMAGE, _FALLBACK_RUNTIME_IMAGE}:
        return
    await _run_docker("rmi", "-f", image_ref)


async def stop_preview(
    project_id: UUID,
    *,
    container_name: str | None = None,
    ephemeral_image: str | None = None,
) -> None:
    """Stop preview container and remove leftover project preview images (never volumes)."""
    if not docker_available():
        return
    name = container_name or preview_container_name(project_id)
    await _remove_container(name)

    protected = {PREVIEW_RUNTIME_IMAGE, _FALLBACK_RUNTIME_IMAGE}
    for image in {ephemeral_image, dev_preview_image_tag(project_id)}:
        if image and image not in protected:
            await _remove_image(image)


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


async def container_logs(container_ref: str, *, tail: int = 80) -> str:
    code, output = await _run_docker("logs", "--tail", str(tail), container_ref)
    if code != 0:
        return output.strip() or f"Could not read logs for {container_ref}"
    return output.strip()


def _build_label_args(project_id: UUID, *, mode: str) -> list[str]:
    args = [
        "--label",
        "factory.preview=1",
        "--label",
        f"factory.project={project_id}",
        "--label",
        f"factory.preview.mode={mode}",
    ]
    if mode == "runtime":
        args.extend(["--label", "factory.preview.runtime=1"])
    return args


async def ensure_runtime_image(log_path: Path | None = None) -> str:
    """Build (once) or reuse the factory-owned preview runtime. Never uses project Dockerfiles."""
    code, _ = await _run_docker("image", "inspect", PREVIEW_RUNTIME_IMAGE)
    if code == 0:
        return PREVIEW_RUNTIME_IMAGE

    logger.info("Building factory preview runtime image %s", PREVIEW_RUNTIME_IMAGE)
    code, output = await _run_docker(
        "build",
        "-t",
        PREVIEW_RUNTIME_IMAGE,
        "-",
        stdin=_RUNTIME_DOCKERFILE.encode(),
        log_path=log_path,
    )
    if code == 0:
        return PREVIEW_RUNTIME_IMAGE

    logger.warning("Runtime image build failed, falling back to %s: %s", _FALLBACK_RUNTIME_IMAGE, output[-500:])
    pull_code, pull_out = await _run_docker("pull", _FALLBACK_RUNTIME_IMAGE, log_path=log_path)
    if pull_code != 0:
        logger.warning("Failed to pull %s: %s", _FALLBACK_RUNTIME_IMAGE, pull_out[-300:])
    return _FALLBACK_RUNTIME_IMAGE


async def ensure_pip_cache_volume() -> None:
    await _run_docker("volume", "create", PIP_CACHE_VOLUME)


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
    spec = PreviewHealthSpec(
        path=str(meta.get("preview_health_path") or DEFAULT_HEALTH_PATH),
        port=int(meta.get("preview_app_port") or DEFAULT_PREVIEW_PORT),
    )
    ip = await container_ip_on_network(name, settings.preview_docker_network)
    host = ip or name
    return f"http://{host}:{spec.port}"


async def _wait_for_health(
    urls: list[str],
    *,
    attempts: int = 90,
    delay: float = 1.0,
) -> tuple[bool, str | None]:
    last_error = "no attempts"
    async with httpx.AsyncClient(timeout=5.0) as client:
        for _ in range(attempts):
            for url in urls:
                try:
                    response = await client.get(url)
                    if 200 <= response.status_code < 300:
                        return True, url
                    last_error = f"{url} -> HTTP {response.status_code}"
                except httpx.HTTPError as exc:
                    last_error = f"{url} -> {exc}"
            await asyncio.sleep(delay)
    return False, last_error


async def _probe_container(
    container_name: str,
    spec: PreviewHealthSpec,
    *,
    attempts: int = 90,
) -> tuple[bool, str]:
    ip = None
    for _ in range(10):
        if not await container_is_running(container_name):
            logs = await container_logs(container_name)
            return False, f"Preview container exited before becoming healthy.\n{logs}"
        ip = await container_ip_on_network(container_name, settings.preview_docker_network)
        if ip:
            break
        await asyncio.sleep(0.5)

    hosts = [h for h in (ip, container_name) if h]
    health_urls = [f"http://{host}:{spec.port}{spec.path}" for host in hosts]
    # Accept a live process even if /health is briefly missing — still prefer the contract path.
    if spec.path != "/":
        health_urls.extend(f"http://{host}:{spec.port}/" for host in hosts)

    ok, matched = await _wait_for_health(health_urls, attempts=attempts)
    if ok:
        return True, matched or health_urls[0]

    logs = await container_logs(container_name)
    running = await container_is_running(container_name)
    state = "still running" if running else "exited"
    return (
        False,
        f"Preview failed health check ({state}) at {spec.path} on port {spec.port}: {matched}.\n{logs}",
    )


async def _copy_repo_to_container(repo_path: Path, container_name: str, log_path: Path | None) -> tuple[bool, str]:
    source = f"{repo_path.resolve()}/."
    dest = f"{container_name}:/app"
    code, output = await _run_docker("cp", source, dest, log_path=log_path)
    if code != 0:
        return False, output or "docker cp failed"
    return True, f"Copied {repo_path} into {container_name}:/app"


def _resource_limit_args() -> list[str]:
    """CPU/memory/pids caps so a runaway generated app can't starve the host."""
    args: list[str] = []
    if settings.preview_memory_limit:
        args.extend(["--memory", settings.preview_memory_limit])
    if settings.preview_cpus:
        args.extend(["--cpus", settings.preview_cpus])
    if settings.preview_pids_limit > 0:
        args.extend(["--pids-limit", str(settings.preview_pids_limit)])
    return args


async def _create_preview_container(
    *,
    project_id: UUID,
    image: str,
    name: str,
    spec: PreviewHealthSpec,
    env_vars: dict[str, str] | None,
    command: list[str] | None,
    mode: str,
    log_path: Path | None,
) -> tuple[bool, str, str | None]:
    ensure_preview_network()
    await _remove_container(name)

    cmd = [
        "create",
        "--name",
        name,
        "--network",
        settings.preview_docker_network,
        "--restart",
        "no",
        *_resource_limit_args(),
        *_build_label_args(project_id, mode=mode),
        "-e",
        f"PORT={spec.port}",
        "-e",
        f"FACTORY_PREVIEW_PATH={gateway_preview_prefix(project_id)}",
    ]
    if mode == "runtime":
        await ensure_pip_cache_volume()
        cmd.extend(["-v", f"{PIP_CACHE_VOLUME}:/root/.cache/pip"])
    for key, value in (env_vars or {}).items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.append(image)
    if command:
        cmd.extend(command)

    code, output = await _run_docker(*cmd, log_path=log_path)
    if code != 0:
        return False, output or "docker create failed", None

    container_id = output.strip()[:12] if output.strip() else None
    return True, container_id or name, container_id


async def start_dev_preview(
    project_id: UUID,
    repo_path: Path,
    log_path: Path,
    *,
    env_vars: dict[str, str] | None = None,
) -> PreviewLaunch:
    """Run the project from source in a factory-owned runtime. Agents never start this."""
    if not docker_available():
        return PreviewLaunch(
            success=False,
            message="Docker is not available for preview",
            failure_kind="infra",
            backend="simulated",
        )

    repo_path = repo_path.resolve()
    main_module = repo_path / "app" / "main.py"
    if not main_module.is_file() and not (repo_path / "main.py").is_file():
        return PreviewLaunch(
            success=False,
            message=f"Preview aborted — missing app/main.py in {repo_path}",
            failure_kind="app",
        )

    spec = load_preview_spec(repo_path)
    name = preview_container_name(project_id)
    await stop_preview(project_id, ephemeral_image=dev_preview_image_tag(project_id))

    image = await ensure_runtime_image(log_path)
    app_module = detect_app_module(repo_path)
    start_cmd = runtime_start_command(
        app_module=app_module,
        port=spec.port,
        root_path=gateway_preview_prefix(project_id),
    )

    created, create_msg, container_id = await _create_preview_container(
        project_id=project_id,
        image=image,
        name=name,
        spec=spec,
        env_vars=env_vars,
        command=["sh", "-c", start_cmd],
        mode="runtime",
        log_path=log_path,
    )
    if not created:
        return PreviewLaunch(
            success=False,
            message=f"Could not create preview container: {create_msg}",
            container_name=name,
            failure_kind="infra",
        )

    copied, copy_msg = await _copy_repo_to_container(repo_path, name, log_path)
    if not copied:
        await _remove_container(name)
        return PreviewLaunch(
            success=False,
            message=f"Could not copy project into preview container: {copy_msg}",
            container_id=container_id,
            container_name=name,
            failure_kind="infra",
        )

    start_code, start_out = await _run_docker("start", name, log_path=log_path)
    if start_code != 0:
        logs = await container_logs(name)
        await _remove_container(name)
        return PreviewLaunch(
            success=False,
            message=f"docker start failed: {start_out}\n{logs}",
            container_id=container_id,
            container_name=name,
            failure_kind="infra",
        )

    healthy, probe_msg = await _probe_container(name, spec)
    if not healthy:
        await _remove_container(name)
        return PreviewLaunch(
            success=False,
            message=probe_msg,
            container_id=container_id,
            container_name=name,
            failure_kind="app",
        )

    return PreviewLaunch(
        success=True,
        message=(
            f"Factory preview {name} running on {settings.preview_docker_network} "
            f"({image}, {app_module} :{spec.port}{spec.path})"
        ),
        container_id=container_id,
        container_name=name,
    )


async def start_docker_preview(
    project_id: UUID,
    image_tag: str,
    *,
    env_vars: dict[str, str] | None = None,
    repo_path: Path | None = None,
    log_path: Path | None = None,
) -> PreviewLaunch:
    """Run a built project image on the preview network (staging / production image)."""
    if not docker_available():
        return PreviewLaunch(
            success=False,
            message="Docker is not available for preview",
            failure_kind="infra",
            backend="simulated",
        )

    spec = load_preview_spec(repo_path) if repo_path else PreviewHealthSpec()
    name = preview_container_name(project_id)
    await stop_preview(project_id, container_name=name)

    created, create_msg, container_id = await _create_preview_container(
        project_id=project_id,
        image=image_tag,
        name=name,
        spec=spec,
        env_vars=env_vars,
        command=None,
        mode="image",
        log_path=log_path,
    )
    if not created:
        return PreviewLaunch(
            success=False,
            message=f"Could not create staging container from {image_tag}: {create_msg}",
            container_name=name,
            failure_kind="infra",
        )

    start_code, start_out = await _run_docker("start", name, log_path=log_path)
    if start_code != 0:
        logs = await container_logs(name)
        await _remove_container(name)
        return PreviewLaunch(
            success=False,
            message=f"docker start failed for {image_tag}: {start_out}\n{logs}",
            container_id=container_id,
            container_name=name,
            failure_kind="infra",
        )

    healthy, probe_msg = await _probe_container(name, spec, attempts=60)
    if not healthy:
        await _remove_container(name)
        return PreviewLaunch(
            success=False,
            message=probe_msg,
            container_id=container_id,
            container_name=name,
            failure_kind="app",
        )

    return PreviewLaunch(
        success=True,
        message=f"Preview container {name} running image {image_tag} on {settings.preview_docker_network}",
        container_id=container_id,
        container_name=name,
    )


async def cleanup_orphan_preview_resources() -> dict[str, int]:
    """Remove leftover preview containers and ephemeral preview images."""
    if not docker_available():
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


async def warmup_preview_runtime() -> None:
    """Pull/build the runtime in the background so the first project preview is fast."""
    if not docker_available():
        return
    try:
        ensure_preview_network()
        await ensure_pip_cache_volume()
        await ensure_runtime_image()
    except Exception:
        logger.exception("Preview runtime warmup failed")


# Backwards-compatible alias
async def cleanup_orphan_preview_containers() -> int:
    result = await cleanup_orphan_preview_resources()
    return result["containers"]
