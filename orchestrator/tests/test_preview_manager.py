from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.preview import restore_preview_meta, snapshot_preview_meta, update_preview_metadata
from app.services.preview_manager import (
    dev_preview_image_tag,
    preview_container_name,
    preview_staging_container_name,
    project_image_repository,
    promote_preview_container,
    start_dev_preview,
    start_docker_preview,
    stop_preview,
)
from app.services.preview_spec import PREVIEW_RUNTIME_IMAGE


def test_dev_preview_image_tag():
    project_id = uuid4()
    assert dev_preview_image_tag(project_id) == f"factory-preview-dev-{str(project_id)[:8]}"


def test_preview_container_name():
    project_id = uuid4()
    assert preview_container_name(project_id) == f"factory-live-{str(project_id)[:8]}"
    assert preview_staging_container_name(project_id) == f"factory-live-{str(project_id)[:8]}-next"


@pytest.mark.asyncio
async def test_promote_preview_container_replaces_canonical():
    project_id = uuid4()
    staging = preview_staging_container_name(project_id)
    with patch("app.services.preview_manager.stop_preview", new_callable=AsyncMock) as stop, patch(
        "app.services.preview_manager._rename_container", new_callable=AsyncMock, return_value=True
    ) as rename:
        assert await promote_preview_container(project_id, staging) is True
        stop.assert_awaited_once()
        rename.assert_awaited_once_with(staging, preview_container_name(project_id))


def test_snapshot_preview_meta_preserves_running_state():
    project_id = uuid4()
    meta = {
        "preview_status": "running",
        "preview_container": preview_container_name(project_id),
        "preview_type": "docker",
        "unrelated": "keep",
    }
    snapshot = snapshot_preview_meta(meta)
    meta["preview_status"] = "failed"
    meta.pop("preview_container", None)
    restore_preview_meta(meta, snapshot)
    assert meta["preview_status"] == "running"
    assert meta["preview_container"] == preview_container_name(project_id)
    assert meta["unrelated"] == "keep"


def test_project_image_repository():
    assert project_image_repository("Clicker Idle Game") == "factory/clicker-idle-game"


@pytest.mark.asyncio
async def test_prune_stale_project_build_images_keeps_current_tag():
    from app.services.preview_manager import prune_stale_project_build_images

    with patch("app.services.preview_manager.docker_available", return_value=True), patch(
        "app.services.preview_manager._run_docker",
        new_callable=AsyncMock,
    ) as run_docker, patch(
        "app.services.preview_manager.images_referenced_by_containers",
        new_callable=AsyncMock,
        return_value=set(),
    ), patch(
        "app.services.preview_manager._remove_image", new_callable=AsyncMock
    ) as remove:
        run_docker.side_effect = [
            (0, "build-old\nbuild-new\n"),
            (0, ""),
        ]
        removed = await prune_stale_project_build_images(
            "demo-app",
            keep_tags={"build-new"},
        )
    assert removed == ["factory/demo-app:build-old"]
    remove.assert_awaited_once_with("factory/demo-app:build-old")


@pytest.mark.asyncio
async def test_prune_stale_project_build_images_skips_referenced():
    from app.services.preview_manager import prune_stale_project_build_images

    with patch("app.services.preview_manager.docker_available", return_value=True), patch(
        "app.services.preview_manager._run_docker",
        new_callable=AsyncMock,
        return_value=(0, "build-old\n"),
    ), patch(
        "app.services.preview_manager.images_referenced_by_containers",
        new_callable=AsyncMock,
        return_value={"factory/demo-app:build-old"},
    ), patch(
        "app.services.preview_manager._remove_image", new_callable=AsyncMock
    ) as remove:
        removed = await prune_stale_project_build_images("demo-app", keep_tags=set())
    assert removed == []
    remove.assert_not_awaited()


@pytest.mark.asyncio
async def test_prune_unused_factory_build_images():
    from app.services.preview_manager import prune_unused_factory_build_images

    with patch("app.services.preview_manager.docker_available", return_value=True), patch(
        "app.services.preview_manager.images_referenced_by_containers",
        new_callable=AsyncMock,
        return_value={"factory-preview-runtime:1"},
    ), patch(
        "app.services.preview_manager._run_docker",
        new_callable=AsyncMock,
        return_value=(0, "factory/app:build-1\nfactory/app:build-2\n"),
    ), patch(
        "app.services.preview_manager._remove_image", new_callable=AsyncMock
    ) as remove:
        removed = await prune_unused_factory_build_images()
    assert len(removed) == 2
    assert remove.await_count == 2


def test_runtime_image_constant_matches_spec():
    assert PREVIEW_RUNTIME_IMAGE.startswith("factory-preview-runtime")


@pytest.mark.asyncio
async def test_stop_preview_never_removes_runtime_image():
    project_id = uuid4()
    with patch("app.services.preview_manager.docker_available", return_value=True), patch(
        "app.services.preview_manager._remove_container", new_callable=AsyncMock
    ) as rm_c, patch(
        "app.services.preview_manager._remove_image", new_callable=AsyncMock
    ) as rm_i:
        await stop_preview(project_id, ephemeral_image=PREVIEW_RUNTIME_IMAGE)
        rm_c.assert_awaited_once()
        # Runtime image must stay cached for the next project.
        for call in rm_i.await_args_list:
            assert PREVIEW_RUNTIME_IMAGE not in call.args
            assert "python:3.12-slim" not in call.args


@pytest.mark.asyncio
async def test_start_dev_preview_uses_runtime_copy_not_project_build(tmp_path):
    project_id = uuid4()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app").mkdir()
    (repo / "app" / "main.py").write_text("app = None\n")
    (repo / "requirements.txt").write_text("fastapi\n")

    with patch("app.services.preview_manager.docker_available", return_value=True), patch(
        "app.services.preview_manager.stop_preview", new_callable=AsyncMock
    ), patch(
        "app.services.preview_manager.ensure_runtime_image",
        new_callable=AsyncMock,
        return_value=PREVIEW_RUNTIME_IMAGE,
    ) as runtime, patch(
        "app.services.preview_manager._create_preview_container",
        new_callable=AsyncMock,
        return_value=(True, "cid", "abc123"),
    ) as create, patch(
        "app.services.preview_manager._copy_repo_to_container",
        new_callable=AsyncMock,
        return_value=(True, "copied"),
    ) as copy, patch(
        "app.services.preview_manager._run_docker",
        new_callable=AsyncMock,
        return_value=(0, "started"),
    ) as run_docker, patch(
        "app.services.preview_manager._probe_container",
        new_callable=AsyncMock,
        return_value=(True, "http://10.0.0.8:8080/health"),
    ):
        result = await start_dev_preview(project_id, repo, tmp_path / "preview.log")

    assert result.success is True
    assert result.container_id == "abc123"
    assert result.ephemeral_image is None
    runtime.assert_awaited_once()
    create.assert_awaited_once()
    assert create.await_args.kwargs["image"] == PREVIEW_RUNTIME_IMAGE
    assert create.await_args.kwargs["mode"] == "runtime"
    copy.assert_awaited_once()
    assert run_docker.await_args.args[0] == "start"
    # Never builds the project's Dockerfile for live preview.
    for call in run_docker.await_args_list:
        assert "build" not in call.args


@pytest.mark.asyncio
async def test_start_dev_preview_missing_app_is_app_failure(tmp_path):
    project_id = uuid4()
    repo = tmp_path / "repo"
    repo.mkdir()
    with patch("app.services.preview_manager.docker_available", return_value=True):
        result = await start_dev_preview(project_id, repo, tmp_path / "preview.log")
    assert result.success is False
    assert result.failure_kind == "app"


@pytest.mark.asyncio
async def test_start_dev_preview_without_docker_is_infra():
    project_id = uuid4()
    with patch("app.services.preview_manager.docker_available", return_value=False):
        result = await start_dev_preview(project_id, Path("/tmp"), Path("/tmp/log"))
    assert result.success is False
    assert result.failure_kind == "infra"


@pytest.mark.asyncio
async def test_start_docker_preview_runs_built_image(tmp_path):
    project_id = uuid4()
    with patch("app.services.preview_manager.docker_available", return_value=True), patch(
        "app.services.preview_manager.stop_preview", new_callable=AsyncMock
    ), patch(
        "app.services.preview_manager._create_preview_container",
        new_callable=AsyncMock,
        return_value=(True, "cid", "abc123"),
    ) as create, patch(
        "app.services.preview_manager._run_docker",
        new_callable=AsyncMock,
        return_value=(0, "started"),
    ), patch(
        "app.services.preview_manager._probe_container",
        new_callable=AsyncMock,
        return_value=(True, "ok"),
    ):
        result = await start_docker_preview(project_id, "factory/demo:build-1", repo_path=tmp_path)

    assert result.success is True
    assert create.await_args.kwargs["image"] == "factory/demo:build-1"
    assert create.await_args.kwargs["mode"] == "image"
    assert create.await_args.kwargs["command"] is None


def test_update_preview_metadata_stores_health_without_ephemeral_image():
    project_id = uuid4()
    meta = {}
    update_preview_metadata(
        meta,
        project_id=project_id,
        port=None,
        preview_type="dev",
        status="running",
        backend="docker",
        container_name=preview_container_name(project_id),
        health_path="/health",
        app_port=8080,
    )
    assert meta["preview_backend"] == "docker"
    assert meta["preview_health_path"] == "/health"
    assert meta["preview_app_port"] == 8080
    assert "preview_ephemeral_image" not in meta
    assert "preview_port" not in meta
