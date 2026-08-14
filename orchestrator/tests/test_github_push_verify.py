from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.github_connection import (
    GitHubTokenError,
    verify_github_token,
    verify_repo_push_access,
    _classic_token_has_push_scope,
)


def test_classic_token_push_scope():
    assert _classic_token_has_push_scope("repo, user") is True
    assert _classic_token_has_push_scope("public_repo") is True
    assert _classic_token_has_push_scope("read:user") is False
    assert _classic_token_has_push_scope("") is True


@pytest.mark.asyncio
@patch("app.services.github_connection.httpx.AsyncClient")
async def test_verify_rejects_read_only_classic_token(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"X-OAuth-Scopes": "read:user"}
    mock_response.json.return_value = {"login": "devuser"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls.return_value = mock_client

    with pytest.raises(GitHubTokenError, match="repo scope"):
        await verify_github_token("ghp_read_only")


@pytest.mark.asyncio
@patch("app.services.github_connection.httpx.AsyncClient")
async def test_verify_repo_push_access_read_only(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "permissions": {"pull": True, "push": False, "admin": False},
        "full_name": "Leemotheyer/turtSlopFactory",
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls.return_value = mock_client

    result = await verify_repo_push_access(
        "ghp_test", "https://github.com/Leemotheyer/turtSlopFactory"
    )
    assert result["can_push"] is False
    assert "read-only" in str(result["message"]).lower()
