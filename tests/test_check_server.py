"""Test that check_server query type doesn't try to access notebooks."""

import pytest

from mcp_jupyter.server import query_notebook


@pytest.mark.integration
def test_check_server_without_notebook(jupyter_server):
    """Test that check_server works without a notebook path."""
    # check_server should work even with a non-existent notebook path
    # because it doesn't actually access the notebook
    result = query_notebook(
        "non_existent_notebook",  # This notebook doesn't exist
        "check_server",
        server_url=jupyter_server,
    )
    assert result == "Jupyter server is running"


@pytest.mark.integration
def test_list_sessions_without_notebook(jupyter_server):
    """Test that list_sessions works without accessing a specific notebook."""
    # list_sessions should work with any notebook path
    # because it doesn't actually access the notebook
    result = query_notebook(
        "any_notebook_name",  # This notebook doesn't need to exist
        "list_sessions",
        server_url=jupyter_server,
    )
    assert isinstance(result, list)
