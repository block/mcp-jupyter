import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest
import requests

from mcp_jupyter.server import (
    NotebookState,
    add_code_cell,
    add_markdown_cell,
    check_jupyter_server,
    delete_cell,
    edit_code_cell,
    execute_cell,
    get_position_index,
    install_packages,
    notebook,
    view_source,
)

# Constants
SERVER_URL = "http://localhost:9999"
TOKEN = "BLOCK"


@pytest.fixture(scope="module")
def jupyter_server():
    """Start a Jupyter server for testing and cleanup after tests"""
    port = 9999
    test_notebooks_dir_name = "test_notebooks_integration"
    test_notebooks_dir = Path(test_notebooks_dir_name)

    # Clean up potential leftovers from previous failed runs
    if test_notebooks_dir.exists():
        shutil.rmtree(test_notebooks_dir)

    # Create a directory for test notebooks
    test_notebooks_dir.mkdir(exist_ok=True)

    # Start the Jupyter server process using uv run, setting cwd
    jupyter_cmd = [
        "uv",
        "run",
        "jupyter",
        "lab",
        f"--port={port}",
        f"--IdentityProvider.token={TOKEN}",
        "--ip=0.0.0.0",
        "--no-browser",
    ]

    # Add --allow-root flag if running as root
    if os.geteuid() == 0:  # Check if running as root
        jupyter_cmd.append("--allow-root")

    # Start the Jupyter server process
    print(f"Starting Jupyter server with command: {' '.join(jupyter_cmd)}")
    server_process = subprocess.Popen(
        jupyter_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid,
    )

    # Wait for the server to start (check if it responds to requests)
    base_url = f"http://localhost:{port}"
    max_retries = 15
    retry_interval = 2

    for _ in range(max_retries):
        try:
            response = requests.get(
                f"{base_url}/api/kernelspecs",
                headers={"Authorization": f"token {TOKEN}"},
            )
            if response.status_code == 200:
                print("Jupyter server started successfully")
                break
        except requests.ConnectionError:
            pass
        time.sleep(retry_interval)
        print("Waiting for Jupyter server to start...")
    else:
        # Server didn't start in time, kill the process and raise an exception
        os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        stdout, stderr = server_process.communicate()
        print(f"Jupyter server stdout: {stdout}")
        print(f"Jupyter server stderr: {stderr}")
        pytest.fail("Jupyter server failed to start in time")

    # Reset notebook state hash
    NotebookState.contents_hash = ""
    # Clear any existing server URLs
    NotebookState.notebook_server_urls = {}

    yield SERVER_URL

    # Cleanup: kill the Jupyter server process and all its children
    print("Shutting down Jupyter server")
    try:
        os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        server_process.wait(timeout=5)
    except ProcessLookupError:
        print("Server process already terminated.")
    except subprocess.TimeoutExpired:
        print("Server process did not terminate gracefully, killing.")
        os.killpg(os.getpgid(server_process.pid), signal.SIGKILL)
        server_process.wait()

    # Remove the entire test directory and its contents
    print(f"Removing test directory: {test_notebooks_dir}")
    if test_notebooks_dir.exists():
        shutil.rmtree(test_notebooks_dir)


@pytest.fixture
def test_notebook(jupyter_server):
    """Create a test notebook with some initial cells for testing."""
    notebook_name = "test_notebooks_integration/test_tools_notebook"

    # Create a notebook with some initial cells - specify server_url here
    result = notebook(
        notebook_name,
        [
            "# Initial cell\nprint('Hello from initial cell')",
            "def add(a, b):\n    return a + b\n\nprint(add(2, 3))",
        ],
        server_url=jupyter_server,
    )

    yield f"{notebook_name}.ipynb"


@pytest.mark.integration
def test_notebook_creation(jupyter_server):
    """Test notebook creation functionality."""
    notebook_name = "test_notebooks_integration/test_creation"

    # Create a new notebook - specify server_url on creation
    result = notebook(notebook_name, [], server_url=jupyter_server)
    assert result is not None
    assert "message" in result
    assert result["message"] == f"Notebook {notebook_name}.ipynb created"

    # Try creating the same notebook again - no need to specify server_url
    result = notebook(notebook_name, [])
    assert result["message"] == f"Notebook {notebook_name}.ipynb already exists"


@pytest.mark.integration
def test_add_code_cell(jupyter_server, test_notebook):
    """Test adding a code cell to a notebook."""
    # Add a simple code cell - test_notebook path is already relative to root
    result = add_code_cell(test_notebook, "x = 10\nprint(f'x = {x}')")

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


@pytest.mark.integration
def test_add_markdown_cell(jupyter_server, test_notebook):
    """Test adding a markdown cell to a notebook."""
    # Add a markdown cell - test_notebook path is already relative to root
    result = add_markdown_cell(
        test_notebook, "# Test Markdown\nThis is a *markdown* cell with **formatting**."
    )

    # Verify result
    assert result["message"] == "Markdown cell added"
    assert not result["error"]


@pytest.mark.integration
def test_view_source(jupyter_server, test_notebook):
    """Test viewing notebook source."""
    # View all cells - test_notebook path is already relative to root
    all_cells = view_source(test_notebook)

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
        specific_cell = view_source(test_notebook, execution_count=str(execution_count))
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
            specific_cell = view_source(test_notebook, position_index=position)
            assert isinstance(specific_cell, dict)
            assert "def add(a, b):" in specific_cell["source"]


@pytest.mark.integration
def test_get_position_index(jupyter_server, test_notebook):
    """Test getting the position index of a cell."""
    # First, explicitly execute a cell to ensure we have at least one with an execution count
    # Add a cell we can easily identify
    add_code_cell(
        test_notebook,
        "# Test cell for get_position_index\nprint('Hello from test cell')",
    )

    # Now get all cells
    all_cells = view_source(test_notebook)

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
        position_by_id = get_position_index(test_notebook, cell_id=cell_id_to_find)
        assert position_by_id == position_to_find

    # If we have an execution count, test that path too
    if execution_count is not None:
        position_by_exec = get_position_index(
            test_notebook, execution_count=str(execution_count)
        )
        assert position_by_exec == position_to_find

    # If we don't have an execution count, just log a message
    else:
        print("Cell has no execution_count, skipping that part of the test")


@pytest.mark.integration
def test_edit_code_cell(jupyter_server, test_notebook):
    """Test editing a code cell."""
    # First, view all cells to find the one we want to edit
    all_cells = view_source(test_notebook)

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
    result = edit_code_cell(test_notebook, position_index, modified_code)

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
    updated_cell = view_source(test_notebook, position_index=position_index)
    assert "def multiply(a, b):" in updated_cell["source"]


@pytest.mark.integration
def test_execute_cell(jupyter_server, test_notebook):
    """Test executing a cell."""
    # First add a cell without executing it - no need to specify server_url
    result = add_code_cell(
        test_notebook, "result = 5 ** 2\nprint(f'5 squared is {result}')", execute=False
    )

    # When execute=False, we get position_index back, not a result dict
    # Get all cells to find the last one (which should be the one we just added)
    all_cells = view_source(test_notebook)
    position_index = len(all_cells) - 1

    # Now execute it - no need to specify server_url
    result = execute_cell(test_notebook, position_index)

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
    add_code_cell(test_notebook, "# This cell will be deleted")

    # Get all cells to find the last one (which should be the one we just added)
    all_cells = view_source(test_notebook)
    position_index = len(all_cells) - 1

    # Delete the cell - no need to specify server_url
    result = delete_cell(test_notebook, position_index)

    # Verify result
    assert result["message"] == "Cell deleted"
    assert not result["error"]

    # Verify the cell was actually deleted
    updated_cells = view_source(test_notebook)
    assert len(updated_cells) == len(all_cells) - 1


@pytest.mark.integration
def test_install_packages(jupyter_server, test_notebook):
    """Test installing packages."""
    # Install a small, common package - no need to specify server_url
    result = install_packages(test_notebook, "pyyaml")

    # Just verify we got a string response
    assert isinstance(result, str)
    assert "pyyaml" in result

    # Verify we can import the package - no need to specify server_url
    import_result = add_code_cell(
        test_notebook, "import yaml\nprint('PyYAML successfully imported')"
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
    result = check_jupyter_server(server_url=SERVER_URL)
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

    result = add_code_cell(test_notebook, code)

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
    dir_name = "new_dir_integration"
    notebook_base_name = "my_subdir_notebook"
    # Path relative to the server root (where jupyter lab was started)
    relative_dir_path = f"test_notebooks_integration/{dir_name}"
    relative_notebook_path = f"{relative_dir_path}/{notebook_base_name}"

    # 1. Attempt to create the notebook (this should also create the directory)
    creation_result = notebook(relative_notebook_path, [], server_url=jupyter_server)
    assert "message" in creation_result
    assert "created" in creation_result["message"]  # Check it was created

    # 2. Verify the directory exists via API
    try:
        dir_response = requests.get(
            f"{jupyter_server}/api/contents/{relative_dir_path}",
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
