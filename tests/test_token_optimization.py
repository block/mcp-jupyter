"""Tests for token optimization features: list_cells and include_outputs."""

import pytest

from mcp_jupyter.server import query_notebook, _strip_outputs


def test_list_cells_returns_compact_metadata(jupyter_server, test_notebook):
    """Test that list_cells returns compact cell metadata."""
    result = query_notebook(
        test_notebook,
        "list_cells",
        server_url=jupyter_server,
    )

    assert isinstance(result, list)
    assert len(result) > 0

    for cell in result:
        assert "position_index" in cell
        assert "cell_type" in cell
        assert "source_preview" in cell
        assert "source_len" in cell
        assert isinstance(cell["position_index"], int)


def test_list_cells_code_cell_has_extra_fields(jupyter_server, test_notebook):
    """Test that code cells in list_cells have execution_count and has_output."""
    result = query_notebook(
        test_notebook,
        "list_cells",
        server_url=jupyter_server,
    )

    code_cells = [c for c in result if c["cell_type"] == "code"]
    assert len(code_cells) > 0

    for cell in code_cells:
        assert "execution_count" in cell
        assert "has_output" in cell


def test_list_cells_source_preview_length(jupyter_server, test_notebook):
    """Test that source_preview_length parameter works."""
    short_result = query_notebook(
        test_notebook,
        "list_cells",
        server_url=jupyter_server,
        source_preview_length=10,
    )

    for cell in short_result:
        assert len(cell["source_preview"]) <= 10


def test_include_outputs_false_strips_outputs(jupyter_server, test_notebook):
    """Test that include_outputs=False removes outputs from cells."""
    result = query_notebook(
        test_notebook,
        "view_source",
        server_url=jupyter_server,
        include_outputs=False,
    )

    for cell in result:
        if cell.get("cell_type") == "code":
            assert cell.get("outputs") == []


def test_strip_outputs_single_cell():
    """Test _strip_outputs on a single cell."""
    cell = {
        "cell_type": "code",
        "source": "print('hello')",
        "outputs": [{"output_type": "stream", "text": "hello\n"}],
    }
    result = _strip_outputs(cell)
    assert result["outputs"] == []
    assert result["source"] == "print('hello')"


def test_strip_outputs_preserves_markdown():
    """Test _strip_outputs doesn't affect markdown cells."""
    cell = {
        "cell_type": "markdown",
        "source": "# Hello",
    }
    result = _strip_outputs(cell)
    assert "outputs" not in result or result.get("outputs") is None


def test_strip_outputs_list():
    """Test _strip_outputs on a list of cells."""
    cells = [
        {"cell_type": "code", "source": "x = 1", "outputs": [{"text": "1"}]},
        {"cell_type": "markdown", "source": "# Title"},
        {"cell_type": "code", "source": "y = 2", "outputs": [{"text": "2"}]},
    ]
    result = _strip_outputs(cells)

    assert len(result) == 3
    assert result[0]["outputs"] == []
    assert result[2]["outputs"] == []
