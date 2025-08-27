"""Test that query_notebook properly updates state hash to avoid stale state errors."""

import pytest

from mcp_jupyter.server import modify_notebook_cells, query_notebook, setup_notebook
from mcp_jupyter.state import NotebookState


@pytest.mark.integration
def test_query_notebook_updates_state_hash(jupyter_server):
    """Test that query_notebook updates the state hash to prevent 'notebook has changed' errors.
    
    This test reproduces the issue where:
    1. Setup a notebook
    2. Add a cell 
    3. View the notebook with query_notebook
    4. Try to add another cell - this would fail without the fix
    
    The fix manually calls NotebookState.update_hash() for view_source and get_position_index
    query types, but not for check_server or list_sessions.
    """
    notebook_path = "test_state_hash"
    server_url = jupyter_server  # jupyter_server fixture already provides the full URL
    
    # Setup notebook
    result = setup_notebook(notebook_path, server_url=server_url)
    assert "created" in result["message"]
    
    # Add initial cell
    result = modify_notebook_cells(
        notebook_path,
        "add_code",
        "print('First cell')",
        execute=False
    )
    assert result == {}  # Empty dict on success for add without execute
    
    # View the notebook - this should update the hash with our fix
    cells = query_notebook(notebook_path, "view_source")
    initial_cell_count = len(cells)
    assert initial_cell_count >= 1, "Should have at least the cell we just added"
    
    # Find our cell (might not be first if notebook had default cells)
    found_first_cell = False
    for cell in cells:
        if "First cell" in cell.get("source", ""):
            found_first_cell = True
            break
    assert found_first_cell, "Should find the 'First cell' we added"
    
    # Verify hash was updated by query_notebook
    stored_hash = NotebookState.contents_hash
    assert stored_hash != "", "query_notebook should have updated the state hash"
    
    # Try to add another cell - this should work now
    # Without the fix, this would fail with "Notebook has changed since you last saw it"
    result = modify_notebook_cells(
        notebook_path,
        "add_code",
        "print('Second cell')",
        execute=False
    )
    assert result == {}  # Should succeed
    
    # Verify both cells are present
    cells = query_notebook(notebook_path, "view_source")
    assert len(cells) == initial_cell_count + 1, "Should have one more cell"
    
    # Check we have both our cells
    found_second_cell = False
    for cell in cells:
        if "Second cell" in cell.get("source", ""):
            found_second_cell = True
            break
    assert found_second_cell, "Should find the 'Second cell' we added"