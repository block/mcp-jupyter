"""Tests for Jupyter notebook path handling, especially with remote Jupyter servers."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_jupyter.notebook import (
    check_notebook_exists,
    create_new_notebook,
    get_notebook_info,
    prepare_notebook,
    start_notebook_kernel,
)
from mcp_jupyter.utils import _ensure_ipynb_extension


def _mock_http_client(side_effects=None, default_response=None):
    """Create a mock httpx.AsyncClient with configurable responses.

    Args:
        side_effects: dict mapping method names to side_effect lists or callables.
        default_response: a default mock response for all methods.
    """
    client = AsyncMock()

    if default_response is None:
        default_response = AsyncMock()
        default_response.status_code = 200
        default_response.json = MagicMock(
            return_value={"name": "test.ipynb", "path": "test.ipynb"}
        )
        default_response.raise_for_status = MagicMock()

    if side_effects:
        for method, effect in side_effects.items():
            getattr(client, method).side_effect = effect
    else:
        client.get.return_value = default_response
        client.put.return_value = default_response
        client.post.return_value = default_response

    return client


class TestNotebookPaths:
    """Test notebook path handling functionality."""

    @pytest.mark.anyio
    async def test_check_notebook_exists_correct_path(self):
        """Test that check_notebook_exists uses the relative path."""
        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("mcp_jupyter.notebook.get_http_client", return_value=mock_client):
            notebook_path = "subfolder/my_notebook.ipynb"
            server_url = "http://remote.server:8888"
            token = "test-token"
            result = await check_notebook_exists(notebook_path, server_url, token)

        mock_client.get.assert_called_once_with(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {token}"},
        )
        assert result is True

    @pytest.mark.anyio
    async def test_create_notebook_correct_path(self):
        """Test that create_new_notebook uses the relative path."""
        mock_resp_200 = AsyncMock()
        mock_resp_200.status_code = 200
        mock_resp_200.raise_for_status = MagicMock()

        mock_resp_201 = AsyncMock()
        mock_resp_201.status_code = 201
        mock_resp_201.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp_200)
        mock_client.put = AsyncMock(return_value=mock_resp_201)

        with patch("mcp_jupyter.notebook.get_http_client", return_value=mock_client):
            notebook_path = "subfolder/my_notebook"
            expected_notebook_path_ext = "subfolder/my_notebook.ipynb"
            server_url = "http://remote.server:8888"
            token = "test-token"

            await create_new_notebook(notebook_path, server_url, token)

        mock_client.get.assert_called_once_with(
            f"{server_url}/api/contents/subfolder",
            headers={"Authorization": f"token {token}"},
        )
        mock_client.put.assert_called_once()
        put_call = mock_client.put.call_args
        assert put_call[0][0] == f"{server_url}/api/contents/{expected_notebook_path_ext}"

    @pytest.mark.anyio
    async def test_create_notebook_creates_directory(self):
        """Test that create_new_notebook creates the directory if it doesn't exist."""
        mock_resp_404 = AsyncMock()
        mock_resp_404.status_code = 404

        mock_resp_201 = AsyncMock()
        mock_resp_201.status_code = 201
        mock_resp_201.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp_404)
        mock_client.put = AsyncMock(return_value=mock_resp_201)

        with patch("mcp_jupyter.notebook.get_http_client", return_value=mock_client):
            notebook_path = "new_folder/my_test_notebook"
            expected_notebook_path_ext = "new_folder/my_test_notebook.ipynb"
            server_url = "http://remote.server:8888"
            token = "test-token"

            await create_new_notebook(notebook_path, server_url, token)

        mock_client.get.assert_called_once_with(
            f"{server_url}/api/contents/new_folder",
            headers={"Authorization": f"token {token}"},
        )

        assert mock_client.put.call_count == 2

        put_calls = mock_client.put.call_args_list

        # First PUT: directory creation
        assert put_calls[0][0][0] == f"{server_url}/api/contents/new_folder"
        assert put_calls[0][1]["json"] == {"type": "directory"}

        # Second PUT: notebook creation
        assert put_calls[1][0][0] == f"{server_url}/api/contents/{expected_notebook_path_ext}"
        assert put_calls[1][1]["json"]["type"] == "notebook"

    @pytest.mark.anyio
    async def test_get_notebook_info_correct_path(self):
        """Test that get_notebook_info uses the relative path."""
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(
            return_value={"name": "info_test.ipynb", "path": "another/folder/info_test.ipynb"}
        )
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("mcp_jupyter.notebook.get_http_client", return_value=mock_client):
            notebook_path = "another/folder/info_test.ipynb"
            server_url = "http://host.com:9999"
            token = "info-token"
            await get_notebook_info(notebook_path, server_url, token)

        mock_client.get.assert_called_once_with(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {token}"},
        )

    @pytest.mark.anyio
    async def test_prepare_notebook_end_to_end(self):
        """Test the prepare_notebook function creates and starts kernel."""
        mock_resp_404 = AsyncMock()
        mock_resp_404.status_code = 404

        mock_resp_201 = AsyncMock()
        mock_resp_201.status_code = 201
        mock_resp_201.raise_for_status = MagicMock()

        mock_resp_sessions_empty = AsyncMock()
        mock_resp_sessions_empty.status_code = 200
        mock_resp_sessions_empty.json = MagicMock(return_value=[])
        mock_resp_sessions_empty.raise_for_status = MagicMock()

        mock_resp_post_session = AsyncMock()
        mock_resp_post_session.status_code = 201
        mock_resp_post_session.json = MagicMock(
            return_value={
                "id": "kernel-123",
                "path": "prep/end_to_end.ipynb",
                "kernel": {"id": "k1"},
            }
        )
        mock_resp_post_session.raise_for_status = MagicMock()

        mock_resp_info = AsyncMock()
        mock_resp_info.status_code = 200
        mock_resp_info.json = MagicMock(
            return_value={"name": "end_to_end.ipynb", "path": "test.ipynb"}
        )
        mock_resp_info.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                mock_resp_404,           # 1. check_notebook_exists
                mock_resp_404,           # 2. create_new_notebook (dir check)
                mock_resp_sessions_empty,  # 3. list_notebook_sessions
                mock_resp_info,          # 4. get_notebook_info
            ]
        )
        mock_client.put = AsyncMock(return_value=mock_resp_201)
        mock_client.post = AsyncMock(return_value=mock_resp_post_session)

        with patch("mcp_jupyter.notebook.get_http_client", return_value=mock_client):
            notebook_path = "prep/end_to_end"
            expected_notebook_path_ext = "prep/end_to_end.ipynb"
            server_url = "http://prepare.it:8888"
            token = "prep-token"
            result = await prepare_notebook(notebook_path, server_url, token)

        get_calls = mock_client.get.call_args_list
        assert len(get_calls) == 4
        assert get_calls[0][0][0] == f"{server_url}/api/contents/{expected_notebook_path_ext}"
        assert get_calls[1][0][0] == f"{server_url}/api/contents/prep"
        assert get_calls[2][0][0] == f"{server_url}/api/sessions"
        assert get_calls[3][0][0] == f"{server_url}/api/contents/{expected_notebook_path_ext}"

        assert mock_client.put.call_count == 2
        put_calls = mock_client.put.call_args_list
        assert put_calls[0][0][0] == f"{server_url}/api/contents/prep"
        assert put_calls[0][1]["json"] == {"type": "directory"}
        assert put_calls[1][0][0] == f"{server_url}/api/contents/{expected_notebook_path_ext}"

        mock_client.post.assert_called_once()
        post_call = mock_client.post.call_args
        assert post_call[0][0] == f"{server_url}/api/sessions"
        assert post_call[1]["json"]["path"] == expected_notebook_path_ext

        assert "message" in result
        assert result["message"].endswith("created")

    @pytest.mark.anyio
    async def test_start_kernel_correct_path(self):
        """Test that start_notebook_kernel uses the relative path and checks sessions."""
        mock_resp_sessions = AsyncMock()
        mock_resp_sessions.status_code = 200
        mock_resp_sessions.json = MagicMock(return_value=[])
        mock_resp_sessions.raise_for_status = MagicMock()

        mock_resp_post = AsyncMock()
        mock_resp_post.status_code = 201
        mock_resp_post.json = MagicMock(
            return_value={
                "id": "kernel-xyz",
                "path": "start/me/up.ipynb",
                "kernel": {"id": "k2"},
            }
        )
        mock_resp_post.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp_sessions)
        mock_client.post = AsyncMock(return_value=mock_resp_post)

        with patch("mcp_jupyter.notebook.get_http_client", return_value=mock_client):
            notebook_path = "start/me/up"
            expected_notebook_path_ext = "start/me/up.ipynb"
            server_url = "http://start.it:8888"
            token = "start-token"
            await start_notebook_kernel(notebook_path, server_url, token)

        mock_client.get.assert_called_once_with(
            f"{server_url}/api/sessions",
            headers={"Authorization": f"token {token}"},
        )

        mock_client.post.assert_called_once()
        post_call = mock_client.post.call_args
        assert post_call[0][0] == f"{server_url}/api/sessions"
        assert post_call[1]["json"]["path"] == expected_notebook_path_ext
        assert post_call[1]["json"]["type"] == "notebook"
