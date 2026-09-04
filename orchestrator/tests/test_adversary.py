from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipeline.stages.adversary import _local_abuse_probe


def _response(status_code: int):
    response = MagicMock()
    response.status_code = status_code
    return response


def _client(side_effect):
    client = AsyncMock()
    client.request = AsyncMock(side_effect=side_effect)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    return client


@pytest.mark.asyncio
async def test_probe_without_preview_returns_no_findings():
    report = await _local_abuse_probe({})
    assert report.findings == []


@pytest.mark.asyncio
async def test_probe_flags_5xx_on_malformed_input():
    responses = [_response(500), _response(422), _response(404), _response(422)]
    with patch(
        "app.pipeline.stages.adversary.httpx.AsyncClient",
        return_value=_client(responses),
    ):
        report = await _local_abuse_probe({"preview_upstream": "http://factory-live-x:8080"})
    assert len(report.findings) == 1
    assert report.findings[0].severity == "high"
    assert "500" in report.findings[0].description


@pytest.mark.asyncio
async def test_probe_passes_well_behaved_app():
    responses = [_response(422), _response(422), _response(404), _response(422)]
    with patch(
        "app.pipeline.stages.adversary.httpx.AsyncClient",
        return_value=_client(responses),
    ):
        report = await _local_abuse_probe({"preview_upstream": "http://factory-live-x:8080"})
    assert report.findings == []
