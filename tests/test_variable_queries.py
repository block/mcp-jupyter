"""Unit tests for list_variables and inspect_variable query types."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_kernel():
    """Return a mock kernel client."""
    kernel = MagicMock()
    return kernel


class TestListVariables:
    def test_list_variables_returns_list(self, mock_kernel):
        """list_variables should return a list of variable dicts."""
        mock_kernel.list_variables.return_value = [
            {"name": "x", "type": ["builtins", "int"], "size": None, "value": "1"},
            {"name": "df", "type": ["pandas.core.frame", "DataFrame"], "size": [10, 3], "value": "..."},
        ]

        with patch("mcp_jupyter.server.get_kernel", return_value=mock_kernel):
            from mcp_jupyter.server import _query_list_variables

            result = _query_list_variables("test.ipynb", server_url="http://localhost:8888")

        assert isinstance(result, list)
        assert len(result) == 2
        names = [v["name"] for v in result]
        assert "x" in names
        assert "df" in names

    def test_list_variables_empty_namespace(self, mock_kernel):
        """list_variables should return an empty list for a fresh kernel."""
        mock_kernel.list_variables.return_value = []

        with patch("mcp_jupyter.server.get_kernel", return_value=mock_kernel):
            from mcp_jupyter.server import _query_list_variables

            result = _query_list_variables("test.ipynb", server_url="http://localhost:8888")

        assert result == []

    def test_list_variables_no_kernel_raises(self):
        """list_variables should raise McpError when no kernel is active."""
        from mcp.shared.exceptions import McpError

        with patch("mcp_jupyter.server.get_kernel", return_value=None):
            from mcp_jupyter.server import _query_list_variables

            with pytest.raises(McpError):
                _query_list_variables("test.ipynb", server_url="http://localhost:8888")


class TestInspectVariable:
    def test_inspect_variable_returns_value(self, mock_kernel):
        """inspect_variable should return the variable name and value."""
        mock_kernel.get_variable.return_value = "42"

        with patch("mcp_jupyter.server.get_kernel", return_value=mock_kernel):
            from mcp_jupyter.server import _query_inspect_variable

            result = _query_inspect_variable(
                "test.ipynb", variable_name="x", server_url="http://localhost:8888"
            )

        assert result["name"] == "x"
        assert result["value"] == "42"
        mock_kernel.get_variable.assert_called_once_with("x")

    def test_inspect_variable_no_kernel_raises(self):
        """inspect_variable should raise McpError when no kernel is active."""
        from mcp.shared.exceptions import McpError

        with patch("mcp_jupyter.server.get_kernel", return_value=None):
            from mcp_jupyter.server import _query_inspect_variable

            with pytest.raises(McpError):
                _query_inspect_variable(
                    "test.ipynb", variable_name="x", server_url="http://localhost:8888"
                )
