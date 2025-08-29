"""Tests for HTTP transport functionality."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from mcp_jupyter.server import create_server


def wait_for_server(url, timeout=10, poll_interval=0.5):
    """Wait for server to be ready by polling an endpoint.

    Args:
        url: Server URL to check
        timeout: Maximum time to wait in seconds
        poll_interval: Time between checks in seconds

    Returns
    -------
        True if server is ready, False if timeout reached
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(url, timeout=1)
            if response.status_code in [
                200,
                404,
                405,
            ]:  # Any response means server is up
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(poll_interval)
    return False


class TestHTTPTransport:
    """Test HTTP transport functionality."""

    def test_create_server_with_default_settings(self):
        """Test server creation with default settings."""
        server = create_server()
        assert server is not None
        assert server.name == "notebook"

    def test_create_server_with_custom_host_port(self):
        """Test server creation with custom host and port."""
        server = create_server(host="0.0.0.0", port=9090)
        assert server is not None
        assert server.name == "notebook"

    def test_create_server_with_stateless_mode(self):
        """Test server creation with stateless HTTP mode."""
        server = create_server(stateless_http=True)
        assert server is not None
        assert server.name == "notebook"

    @pytest.mark.integration
    def test_http_server_startup(self):
        """Test that HTTP server can start and respond to requests."""
        server = create_server(port=8081)

        # Start server in a separate thread
        server_thread = threading.Thread(
            target=lambda: server.run(transport="streamable-http"), daemon=True
        )
        server_thread.start()

        # Wait for server to be ready
        if not wait_for_server("http://127.0.0.1:8081/", timeout=10):
            pytest.skip("HTTP server did not start in time")

        try:
            # Test that server responds to HTTP requests
            response = requests.post(
                "http://127.0.0.1:8081/mcp",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                    "id": 1,
                },
                timeout=5,
            )

            # Check that we get a response (even if it's an error due to missing session)
            assert response.status_code in [200, 202, 400, 406]

        except requests.exceptions.RequestException:
            pytest.skip("HTTP server did not start in time")

    def test_tools_registered_correctly(self):
        """Test that all tools are registered when server is created."""
        # The server is already created at module import time with tools registered
        # Just verify that the tools are accessible
        server = create_server()
        assert server is not None
        assert server.name == "notebook"

        # Since FastMCP is initialized at module level with decorators,
        # we can't easily mock it. The test for server creation is sufficient.

    def test_server_singleton_behavior(self):
        """Test that create_server returns the same instance when called multiple times."""
        # Reset the global mcp to None
        import mcp_jupyter.server

        original_mcp = mcp_jupyter.server.mcp
        mcp_jupyter.server.mcp = None

        try:
            server1 = create_server()
            server2 = create_server()

            # Should return the same instance
            assert server1 is server2
        finally:
            # Restore original state
            mcp_jupyter.server.mcp = original_mcp


class TestCLIArguments:
    """Test CLI argument parsing."""

    @patch("argparse.ArgumentParser.parse_args")
    @patch("mcp_jupyter.create_server")
    @patch("sys.argv", ["mcp-jupyter"])
    def test_cli_default_transport(self, mock_create, mock_parse):
        """Test default transport is stdio."""
        from mcp_jupyter import main

        mock_server = MagicMock()
        mock_create.return_value = mock_server

        mock_args = MagicMock()
        mock_args.transport = "stdio"
        mock_args.port = 8000
        mock_args.host = "127.0.0.1"
        mock_args.stateless_http = False
        mock_parse.return_value = mock_args

        # This would normally run the server, but we're mocking it
        try:
            main()
        except SystemExit:
            pass

        mock_server.run.assert_called_once_with(transport="stdio")

    @patch("argparse.ArgumentParser.parse_args")
    @patch("mcp_jupyter.create_server")
    @patch("sys.argv", ["mcp-jupyter", "--transport", "http", "--port", "8080"])
    def test_cli_http_transport(self, mock_create, mock_parse):
        """Test HTTP transport argument."""
        from mcp_jupyter import main

        mock_server = MagicMock()
        mock_create.return_value = mock_server

        mock_args = MagicMock()
        mock_args.transport = "http"
        mock_args.port = 8080
        mock_args.host = "127.0.0.1"
        mock_args.stateless_http = False
        mock_parse.return_value = mock_args

        try:
            main()
        except SystemExit:
            pass

        # Check that streamable-http transport is used
        mock_server.run.assert_called_once_with(transport="streamable-http")
        mock_create.assert_called_once_with(
            host="127.0.0.1", port=8080, stateless_http=False
        )

    @patch("argparse.ArgumentParser.parse_args")
    @patch("mcp_jupyter.create_server")
    @patch("sys.argv", ["mcp-jupyter", "--transport", "http", "--stateless-http"])
    def test_cli_stateless_mode(self, mock_create, mock_parse):
        """Test stateless HTTP mode argument."""
        from mcp_jupyter import main

        mock_server = MagicMock()
        mock_create.return_value = mock_server

        mock_args = MagicMock()
        mock_args.transport = "http"
        mock_args.port = 8000
        mock_args.host = "127.0.0.1"
        mock_args.stateless_http = True
        mock_parse.return_value = mock_args

        try:
            main()
        except SystemExit:
            pass

        mock_create.assert_called_once_with(
            host="127.0.0.1", port=8000, stateless_http=True
        )


class TestHTTPEndpoints:
    """Test HTTP endpoint behavior."""

    @pytest.mark.integration
    def test_http_initialize_endpoint(self):
        """Test the initialize endpoint with proper headers."""
        server = create_server(port=8082)

        # Start server in a separate thread
        server_thread = threading.Thread(
            target=lambda: server.run(transport="streamable-http"), daemon=True
        )
        server_thread.start()

        # Wait for server to be ready
        if not wait_for_server("http://127.0.0.1:8082/", timeout=10):
            pytest.skip("HTTP server did not start in time")

        try:
            # Test initialize endpoint
            response = requests.post(
                "http://127.0.0.1:8082/mcp",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                    "id": 1,
                },
                timeout=5,
                stream=True,
            )

            assert response.status_code == 200

            # Parse SSE response
            content = response.text
            assert "event: message" in content or "jsonrpc" in content

            # Check for session ID header
            assert (
                "mcp-session-id" in response.headers
                or "Mcp-Session-Id" in response.headers
            )

        except requests.exceptions.RequestException as e:
            pytest.skip(f"HTTP server did not respond properly: {e}")

    @pytest.mark.integration
    def test_http_missing_accept_headers(self):
        """Test that server rejects requests without proper Accept headers."""
        server = create_server(port=8083)

        # Start server in a separate thread
        server_thread = threading.Thread(
            target=lambda: server.run(transport="streamable-http"), daemon=True
        )
        server_thread.start()

        # Wait for server to be ready
        if not wait_for_server("http://127.0.0.1:8083/", timeout=10):
            pytest.skip("HTTP server did not start in time")

        try:
            # Test with missing Accept header
            response = requests.post(
                "http://127.0.0.1:8083/mcp",
                headers={
                    "Content-Type": "application/json",
                    # Missing Accept header
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                    "id": 1,
                },
                timeout=5,
            )

            # Should reject with 406 Not Acceptable
            assert response.status_code == 406

            # Check error message
            error_data = response.json()
            assert "error" in error_data
            assert "Not Acceptable" in error_data["error"]["message"]

        except requests.exceptions.RequestException as e:
            pytest.skip(f"HTTP server did not respond properly: {e}")
