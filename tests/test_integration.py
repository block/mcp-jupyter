import pytest

from mcp_jupyter.server import (
    execute_notebook_code,
    modify_notebook_cells,
    query_notebook,
    setup_notebook,
)

# TOKEN constant
TOKEN = "BLOCK"


# Server fixtures are now provided by conftest.py


# Test notebook fixture is now provided by conftest.py


@pytest.mark.integration
def test_notebook_creation(jupyter_server):
    """Test notebook creation functionality."""
    notebook_name = "test_creation"

    # Create a new notebook - specify server_url on creation
    result = setup_notebook(notebook_name, [], server_url=jupyter_server)
    assert result is not None
    assert "message" in result
    assert result["message"] == f"Notebook {notebook_name}.ipynb created"

    # Try creating the same notebook again - no need to specify server_url
    result = setup_notebook(notebook_name, [])
    assert result["message"] == f"Notebook {notebook_name}.ipynb already exists"


@pytest.mark.integration
def test_add_code_cell(jupyter_server, test_notebook):
    """Test adding a code cell to a notebook."""
    # Add a simple code cell - test_notebook path is already relative to root
    result = modify_notebook_cells(
        test_notebook, "add_code", "x = 10\nprint(f'x = {x}')"
    )

    # Verify execution results
    assert "execution_count" in result
    assert "outputs" in result
    assert len(result["outputs"]) > 0
    assert result["status"] == "ok"

    # Check output content
    output_text = ""
    for output in result["outputs"]:
        if output["output_type"] == "stream":
            output_text += output["text"]

    assert "x = 10" in output_text

    # Test adding cell at specific position (not at the bottom)
    # First get current cell count
    all_cells_before = query_notebook(test_notebook, "view_source")
    initial_count = len(all_cells_before)

    # Add a cell at position 1 (second position)
    positioned_result = modify_notebook_cells(
        test_notebook,
        "add_code",
        "y = 20\nprint(f'y = {y}')",
        position_index=1,
        execute=False,
    )

    # Verify the cell was added (should be empty result since execute=False)
    assert positioned_result == {}

    # Check that the cell was inserted at the correct position
    all_cells_after = query_notebook(test_notebook, "view_source")
    assert len(all_cells_after) == initial_count + 1

    # Verify the cell at position 1 contains our new content
    inserted_cell = all_cells_after[1]
    assert inserted_cell["cell_type"] == "code"
    assert "y = 20" in inserted_cell["source"]
    assert inserted_cell["execution_count"] is None  # Not executed


@pytest.mark.integration
def test_add_markdown_cell(jupyter_server, test_notebook):
    """Test adding a markdown cell to a notebook."""
    # Add a markdown cell - test_notebook path is already relative to root
    result = modify_notebook_cells(
        test_notebook,
        "add_markdown",
        "# Test Markdown\nThis is a *markdown* cell with **formatting**.",
    )

    # Verify result
    assert result["message"] == "Markdown cell added"
    assert not result["error"]


@pytest.mark.integration
def test_edit_markdown_cell(jupyter_server, test_notebook):
    """Test editing a markdown cell."""
    # First add a markdown cell to edit
    add_result = modify_notebook_cells(
        test_notebook,
        "add_markdown",
        cell_content="# Original Title\n\nOriginal content.",
    )
    assert add_result["message"] == "Markdown cell added"

    # Get all cells to find the markdown cell we just added
    all_cells = query_notebook(test_notebook, "view_source")

    # Find the markdown cell by content
    markdown_position = None
    for i, cell in enumerate(all_cells):
        if cell.get("cell_type") == "markdown" and "Original Title" in cell.get(
            "source", ""
        ):
            markdown_position = i
            break

    assert markdown_position is not None, (
        "Could not find the markdown cell we just added"
    )

    # Edit the markdown cell
    edit_result = modify_notebook_cells(
        test_notebook,
        "edit_markdown",
        cell_content="# Updated Title\n\nThis content has been updated!",
        position_index=markdown_position,
    )

    # Verify edit result
    assert edit_result["message"] == "Markdown cell edited"
    assert not edit_result["error"]

    # Verify the cell was actually changed
    updated_cell = query_notebook(
        test_notebook, "view_source", position_index=markdown_position
    )
    assert "Updated Title" in updated_cell["source"]
    assert "This content has been updated!" in updated_cell["source"]
    assert updated_cell["cell_type"] == "markdown"


@pytest.mark.integration
def test_view_source(jupyter_server, test_notebook):
    """Test viewing notebook source."""
    # View all cells - test_notebook path is already relative to root
    all_cells = query_notebook(test_notebook, "view_source")

    # Verify we got a list of cells
    assert isinstance(all_cells, list)
    assert len(all_cells) >= 2  # Should have at least our 2 initial cells

    # Find the cell with the add function by content, not by execution count
    cell_with_add_function = None
    for cell in all_cells:
        if cell.get("source") and "def add(a, b):" in cell.get("source"):
            cell_with_add_function = cell
            break

    assert cell_with_add_function is not None
    execution_count = cell_with_add_function.get("execution_count")

    # Now view just that specific cell by execution count (if it has one)
    if execution_count is not None:
        specific_cell = query_notebook(
            test_notebook, "view_source", execution_count=int(execution_count)
        )
        assert isinstance(specific_cell, dict)
        assert "def add(a, b):" in specific_cell["source"]
    else:
        # If no execution count (cell might not have been executed yet),
        # find the cell by position instead
        position = None
        for i, cell in enumerate(all_cells):
            if cell.get("source") and "def add(a, b):" in cell.get("source"):
                position = i
                break

        if position is not None:
            specific_cell = query_notebook(
                test_notebook, "view_source", position_index=position
            )
            assert isinstance(specific_cell, dict)
            assert "def add(a, b):" in specific_cell["source"]


@pytest.mark.integration
def test_get_position_index(jupyter_server, test_notebook):
    """Test getting the position index of a cell."""
    # First, explicitly execute a cell to ensure we have at least one with an execution count
    # Add a cell we can easily identify
    modify_notebook_cells(
        test_notebook,
        "add_code",
        "# Test cell for get_position_index\nprint('Hello from test cell')",
    )

    # Now get all cells
    all_cells = query_notebook(test_notebook, "view_source")

    # Find our cell either by content or by execution count
    position_to_find = None
    cell_id_to_find = None

    for i, cell in enumerate(all_cells):
        if cell.get("source") and "Test cell for get_position_index" in cell.get(
            "source"
        ):
            position_to_find = i
            cell_id_to_find = cell.get("id")
            execution_count = cell.get("execution_count")
            break

    assert position_to_find is not None, "Could not find our test cell"

    # Try to get position by content (using cell_id)
    if cell_id_to_find:
        position_by_id = query_notebook(
            test_notebook, "get_position_index", cell_id=cell_id_to_find
        )
        assert position_by_id == position_to_find

    # If we have an execution count, test that path too
    if execution_count is not None:
        position_by_exec = query_notebook(
            test_notebook, "get_position_index", execution_count=int(execution_count)
        )
        assert position_by_exec == position_to_find

    # If we don't have an execution count, just log a message
    else:
        print("Cell has no execution_count, skipping that part of the test")


@pytest.mark.integration
def test_edit_code_cell(jupyter_server, test_notebook):
    """Test editing a code cell."""
    # First, view all cells to find the one we want to edit
    all_cells = query_notebook(test_notebook, "view_source")

    # Find the cell with the add function by content
    position_index = None
    for i, cell in enumerate(all_cells):
        if cell.get("source") and "def add(a, b):" in cell.get("source"):
            position_index = i
            break

    # If we didn't find the add function cell, use the first code cell
    if position_index is None:
        for i, cell in enumerate(all_cells):
            if cell.get("cell_type") == "code":
                position_index = i
                break

    assert position_index is not None, "Could not find a code cell to edit"

    # Edit the cell
    modified_code = "def multiply(a, b):\n    return a * b\n\nprint(multiply(3, 4))"
    result = modify_notebook_cells(
        test_notebook, "edit_code", modified_code, position_index
    )

    # Verify execution results
    assert "execution_count" in result
    assert "outputs" in result
    assert result["status"] == "ok"

    # Check output content
    output_text = ""
    for output in result["outputs"]:
        if output["output_type"] == "stream":
            output_text += output["text"]

    assert "12" in output_text  # 3 * 4 = 12

    # Verify the cell was actually changed
    updated_cell = query_notebook(
        test_notebook, "view_source", position_index=position_index
    )
    assert "def multiply(a, b):" in updated_cell["source"]

    # Test editing by execution_count (two-step workflow)
    # Get the execution_count of the cell we just edited
    execution_count = updated_cell.get("execution_count")
    assert execution_count is not None, (
        "Cell should have execution_count after being executed"
    )

    # Step 1: Find position by execution_count
    found_position = query_notebook(
        test_notebook, "get_position_index", execution_count=execution_count
    )
    assert found_position == position_index, (
        "execution_count lookup should return same position"
    )

    # Step 2: Edit the cell using the found position
    modified_code2 = "def divide(a, b):\n    return a / b\n\nprint(divide(12, 3))"
    result2 = modify_notebook_cells(
        test_notebook, "edit_code", modified_code2, found_position
    )

    # Verify the second edit worked
    assert "execution_count" in result2
    assert result2["status"] == "ok"

    # Check output content
    output_text2 = ""
    for output in result2["outputs"]:
        if output["output_type"] == "stream":
            output_text2 += output["text"]
    assert "4.0" in output_text2  # 12 / 3 = 4.0

    # Verify the cell content changed again
    final_cell = query_notebook(
        test_notebook, "view_source", position_index=position_index
    )
    assert "def divide(a, b):" in final_cell["source"]


@pytest.mark.integration
def test_execute_cell(jupyter_server, test_notebook):
    """Test executing a cell."""
    # First add a cell without executing it - no need to specify server_url
    result = modify_notebook_cells(
        test_notebook,
        "add_code",
        "result = 5 ** 2\nprint(f'5 squared is {result}')",
        execute=False,
    )

    # When execute=False, we get position_index back, not a result dict
    # Get all cells to find the last one (which should be the one we just added)
    all_cells = query_notebook(test_notebook, "view_source")
    position_index = len(all_cells) - 1

    # Now execute it - no need to specify server_url
    result = execute_notebook_code(test_notebook, "execute_cell", position_index)

    # Verify execution results
    assert "execution_count" in result
    assert "outputs" in result
    assert result["status"] == "ok"

    # Check output content
    output_text = ""
    for output in result["outputs"]:
        if output["output_type"] == "stream":
            output_text += output["text"]

    assert "5 squared is 25" in output_text


@pytest.mark.integration
def test_delete_cell(jupyter_server, test_notebook):
    """Test deleting a cell."""
    # Add a cell that we'll delete - no need to specify server_url
    modify_notebook_cells(test_notebook, "add_code", "# This cell will be deleted")

    # Get all cells to find the last one (which should be the one we just added)
    all_cells = query_notebook(test_notebook, "view_source")
    position_index = len(all_cells) - 1

    # Delete the cell - no need to specify server_url
    result = modify_notebook_cells(
        test_notebook, "delete", position_index=position_index
    )

    # Verify result
    assert result["message"] == "Cell deleted"
    assert not result["error"]

    # Verify the cell was actually deleted
    updated_cells = query_notebook(test_notebook, "view_source")
    assert len(updated_cells) == len(all_cells) - 1


@pytest.mark.integration
def test_install_packages(jupyter_server, test_notebook):
    """Test installing packages."""
    # Install a small, common package - no need to specify server_url
    result = execute_notebook_code(
        test_notebook, "install_packages", package_names="pyyaml"
    )

    # Just verify we got a string response
    assert isinstance(result, str)
    assert "pyyaml" in result

    # Verify we can import the package - no need to specify server_url
    import_result = modify_notebook_cells(
        test_notebook, "add_code", "import yaml\nprint('PyYAML successfully imported')"
    )

    # Check output content
    output_text = ""
    for output in import_result["outputs"]:
        if output["output_type"] == "stream":
            output_text += output["text"]

    assert "successfully imported" in output_text


@pytest.mark.integration
def test_check_jupyter_server(jupyter_server):
    """Test that check_jupyter_server correctly verifies server connectivity."""
    # We still need to specify server_url here since this function doesn't use notebook_path
    result = query_notebook("", "check_server", server_url=jupyter_server)
    assert result == "Jupyter server is running"


@pytest.mark.integration
def test_complex_code_execution(jupyter_server, test_notebook):
    """Test executing more complex code with multiple outputs."""
    # Add a cell with multiple print statements and a calculation - no need to specify server_url
    code = """
    import math
    
    def calculate_circle_properties(radius):
        area = math.pi * radius ** 2
        circumference = 2 * math.pi * radius
        return area, circumference
    
    radius = 5
    area, circumference = calculate_circle_properties(radius)
    
    print(f"Radius: {radius}")
    print(f"Area: {area:.2f}")
    print(f"Circumference: {circumference:.2f}")
    """

    result = modify_notebook_cells(test_notebook, "add_code", code)

    # Verify execution results
    assert result["status"] == "ok"

    # Check output content
    output_text = ""
    for output in result["outputs"]:
        if output["output_type"] == "stream":
            output_text += output["text"]

    assert "Radius: 5" in output_text
    assert "Area: 78.54" in output_text
    assert "Circumference: 31.42" in output_text


@pytest.mark.integration
def test_notebook_creation_with_new_directory(jupyter_server):
    """Test that creating a notebook in a non-existent directory works."""
    import requests

    dir_name = "new_dir_integration"
    notebook_base_name = "my_subdir_notebook"
    # Path relative to the server root (where jupyter lab was started)
    relative_notebook_path = f"{dir_name}/{notebook_base_name}"

    # 1. Attempt to create the notebook (this should also create the directory)
    creation_result = setup_notebook(
        relative_notebook_path, [], server_url=jupyter_server
    )
    assert "message" in creation_result
    assert "created" in creation_result["message"]  # Check it was created

    # 2. Verify the directory exists via API
    try:
        dir_response = requests.get(
            f"{jupyter_server}/api/contents/{dir_name}",
            headers={"Authorization": f"token {TOKEN}"},
        )
        dir_response.raise_for_status()  # Should be 200 OK
        dir_data = dir_response.json()
        assert dir_data["type"] == "directory"
        assert dir_data["name"] == dir_name
    except requests.RequestException as e:
        pytest.fail(f"Failed to verify directory existence via API: {e}")

    # 3. Verify the notebook file exists via API
    try:
        nb_response = requests.get(
            f"{jupyter_server}/api/contents/{relative_notebook_path}.ipynb",
            headers={"Authorization": f"token {TOKEN}"},
        )
        nb_response.raise_for_status()  # Should be 200 OK
        nb_data = nb_response.json()
        assert nb_data["type"] == "notebook"
        assert nb_data["name"] == f"{notebook_base_name}.ipynb"
    except requests.RequestException as e:
        pytest.fail(f"Failed to verify notebook existence via API: {e}")
