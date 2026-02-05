"""Test that check_server query type doesn't try to access notebooks."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from mcp_jupyter.rest_client import NotebookClient
from mcp_jupyter.server import query_notebook


async def test_check_server_without_notebook(jupyter_server):
    """Test that check_server works without a notebook path."""
    result = await query_notebook(
        "non_existent_notebook",
        "check_server",
        server_url=jupyter_server,
    )
    assert result == "Jupyter server is running"


async def test_list_sessions_without_notebook(jupyter_server):
    """Test that list_sessions works without accessing a specific notebook."""
    result = await query_notebook(
        "any_notebook_name",
        "list_sessions",
        server_url=jupyter_server,
    )
    assert isinstance(result, list)


async def test_get_default_kernel_info(jupyter_server):
    """Test that kernel info can be retrieved from the server."""
    client = NotebookClient(
        server_url=jupyter_server,
        notebook_path="test_kernel.ipynb",
        token="BLOCK",
    )

    kernelspec, language_info = await client._get_default_kernel_info()

    assert isinstance(kernelspec, dict)
    assert "display_name" in kernelspec
    assert "language" in kernelspec
    assert "name" in kernelspec

    assert isinstance(language_info, dict)
    assert "name" in language_info

    assert kernelspec["language"] == "python"
    assert language_info["name"] == "python"
    assert "python" in kernelspec["display_name"].lower()


async def test_reconnect_interval_configured():
    """Test that KernelClient is initialized with reconnect_interval=5."""
    with patch("mcp_jupyter.server.KernelClient") as mock_kernel_client:
        with patch(
            "mcp_jupyter.server.get_kernel_id",
            new_callable=AsyncMock,
            return_value="mock-kernel-id",
        ):
            mock_instance = Mock()
            mock_instance.kernel_id = "mock-kernel-id"
            mock_instance.start = Mock()
            mock_instance.stop = Mock()
            mock_kernel_client.return_value = mock_instance

            from mcp_jupyter.server import get_kernel

            await get_kernel("test_notebook.ipynb", server_url="http://localhost:8888")

            mock_kernel_client.assert_called_once()
            call_kwargs = mock_kernel_client.call_args.kwargs
            assert "client_kwargs" in call_kwargs
            assert call_kwargs["client_kwargs"] == {"reconnect_interval": 5}


async def test_check_server_timeout():
    """Test that check_server returns descriptive message on timeout."""
    mock_response = AsyncMock()
    mock_response.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("mcp_jupyter.server.get_http_client", return_value=mock_response):
        result = await query_notebook(
            "nb", "check_server", server_url="http://localhost:8888"
        )
        assert result == "Jupyter server is not accessible (timeout)"


async def test_check_server_connection_error():
    """Test that check_server returns descriptive message on connection error."""
    mock_response = AsyncMock()
    mock_response.get = AsyncMock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with patch("mcp_jupyter.server.get_http_client", return_value=mock_response):
        result = await query_notebook(
            "nb", "check_server", server_url="http://localhost:8888"
        )
        assert result == "Jupyter server is not accessible (connection error)"
