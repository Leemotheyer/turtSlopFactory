from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest

from app.services.preview import update_preview_metadata
from app.services.preview_manager import (
    dev_preview_image_tag,
    preview_container_name,
    start_dev_preview,
    stop_preview,
)


def test_dev_preview_image_tag():
    project_id = uuid4()
    assert dev_preview_image_tag(project_id) == f"factory-preview-dev-{str(project_id)[:8]}"


def test_preview_container_name():
    project_id = uuid4()
    assert preview_container_name(project_id) == f"factory-live-{str(project_id)[:8]}"


@pytest.mark.asyncio
async def test_stop_preview_removes_container_and_ephemeral_image(tmp_path):
    project_id = uuid4()
    image = dev_preview_image_tag(project_id)
    with patch("app.services.preview_manager._remove_container", new_callable=AsyncMock) as rm_c, patch(
        "app.services.preview_manager._remove_image", new_callable=AsyncMock
    ) as rm_i:
        await stop_preview(project_id, ephemeral_image=image)
        rm_c.assert_awaited_once()
        assert rm_i.await_count >= 1


@pytest.mark.asyncio
async def test_start_dev_preview_builds_and_runs_without_mount(tmp_path):
    project_id = uuid4()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app").mkdir()
    (repo / "app" / "main.py").write_text(
        'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/health")\ndef health():\n    return {"status": "ok"}\n'
    )
    (repo / "requirements.txt").write_text("fastapi\nuvicorn\n")

    with patch("app.services.preview_manager.Path") as path_cls, patch(
        "app.services.preview_manager.stop_preview", new_callable=AsyncMock
    ), patch(
        "app.services.preview_manager._build_ephemeral_image",
        new_callable=AsyncMock,
        return_value=(True, "built"),
    ) as build, patch(
        "app.services.preview_manager._run_preview_container",
        new_callable=AsyncMock,
        return_value=(True, "running", "abc123"),
    ) as run:
        path_cls.return_value.exists.return_value = True
        ok, msg, cid, image = await start_dev_preview(project_id, repo, tmp_path / "preview.log")

    assert ok is True
    assert cid == "abc123"
    assert image == dev_preview_image_tag(project_id)
    build.assert_awaited_once()
    run.assert_awaited_once()
    assert run.await_args.kwargs.get("ephemeral") is True


def test_update_preview_metadata_stores_ephemeral_image():
    project_id = uuid4()
    meta = {}
    image = dev_preview_image_tag(project_id)
    update_preview_metadata(
        meta,
        project_id=project_id,
        port=None,
        preview_type="dev",
        status="running",
        backend="docker",
        container_name=preview_container_name(project_id),
        ephemeral_image=image,
    )
    assert meta["preview_backend"] == "docker"
    assert meta["preview_ephemeral_image"] == image
    assert "preview_port" not in meta
