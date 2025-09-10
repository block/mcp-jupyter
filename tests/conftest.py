"""Shared test configuration with single warm server for session reuse."""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest
import requests

# Fixtures for MCP Jupyter integration tests

# Constants
SERVER_PORT = 9999
TOKEN = "BLOCK"

# LLM test constants
LLM_SERVER_PORT = 10000


def _start_jupyter_server(port: int, test_dir_name: str, server_type: str = ""):
    """Start a Jupyter server with given configuration.

    Args:
        port: Port number for the server
        test_dir_name: Name of the test directory
        server_type: Optional prefix for log messages (e.g., "LLM ")

    Returns
    -------
        Server URL string
    """
    test_notebooks_dir = Path(test_dir_name)
    server_url = f"http://localhost:{port}"

    # Clean up potential leftovers from previous failed runs
    if test_notebooks_dir.exists():
        shutil.rmtree(test_notebooks_dir)

    # Create a directory for test notebooks
    test_notebooks_dir.mkdir(exist_ok=True)

    # Start the Jupyter server process using uv run
    jupyter_cmd = [
        "uv",
        "run",
        "jupyter",
        "lab",
        f"--port={port}",
        f"--IdentityProvider.token={TOKEN}",
        "--ip=0.0.0.0",
        "--no-browser",
        "--ServerApp.disable_check_xsrf=True",  # Skip XSRF checks for faster startup
        "--ServerApp.allow_origin='*'",  # Allow all origins
        "--LabServerApp.open_browser=False",  # Ensure no browser attempts
        f"--ServerApp.root_dir={test_notebooks_dir.absolute()}",  # Set root directory
    ]

    # Add --allow-root flag if running as root (handle systems without geteuid)
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:  # Check if running as root
            jupyter_cmd.append("--allow-root")
    except (AttributeError, OSError):
        # On systems without geteuid (Windows) or other issues, add --allow-root anyway
        jupyter_cmd.append("--allow-root")

    # Start the Jupyter server process
    print(f"Starting {server_type}Jupyter server on port {port}...")
    server_process = subprocess.Popen(
        jupyter_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid,
    )

    # Wait for the server to start with optimized polling
    max_retries = 30  # More retries for reliability
    retry_interval = 0.25  # Check every 250ms for faster detection
    initial_wait = 0.5  # Brief initial delay

    time.sleep(initial_wait)

    for attempt in range(max_retries):
        try:
            # Use /api/sessions for faster response than /api/kernelspecs
            response = requests.get(
                f"{server_url}/api/sessions",
                headers={"Authorization": f"token {TOKEN}"},
                timeout=1,  # Shorter timeout for faster failure detection
            )
            if response.status_code == 200:
                print(
                    f"{server_type}Jupyter server started successfully (attempt {attempt + 1})"
                )
                break
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(retry_interval)
        if attempt % 8 == 0:  # Print every 2 seconds
            print(
                f"Waiting for {server_type.lower()}server to start... (attempt {attempt + 1}/{max_retries})"
            )
    else:
        # Server didn't start in time, kill the process and raise an exception
        try:
            os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass  # Process already terminated
        stdout, stderr = server_process.communicate()
        print(f"{server_type}Jupyter server stdout: {stdout}")
        print(f"{server_type}Jupyter server stderr: {stderr}")
        pytest.fail(f"{server_type}Jupyter server failed to start in time")

    # Reset notebook state hash at session start
    try:
        from mcp_jupyter.server import NotebookState

        NotebookState.contents_hash = ""
        NotebookState.notebook_server_urls = {}
    except ImportError:
        print("Warning: Could not import NotebookState, state management disabled")

    return server_url, server_process, test_notebooks_dir


def _cleanup_jupyter_server(
    server_process, test_notebooks_dir: Path, server_type: str = ""
):
    """Clean up a Jupyter server and its test directory.

    Args:
        server_process: The subprocess.Popen server process
        test_notebooks_dir: Path to the test directory to remove
        server_type: Optional prefix for log messages (e.g., "LLM ")
    """
    # Cleanup: kill the Jupyter server process and all its children
    print(f"Shutting down {server_type}Jupyter server")
    try:
        os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        server_process.wait(timeout=5)
    except ProcessLookupError:
        print(f"{server_type}Server process already terminated.")
    except subprocess.TimeoutExpired:
        print(f"{server_type}Server process did not terminate gracefully, killing.")
        os.killpg(os.getpgid(server_process.pid), signal.SIGKILL)
        server_process.wait()

    # Remove the entire test directory and its contents
    print(f"Removing {server_type.lower()}test directory: {test_notebooks_dir}")
    if test_notebooks_dir.exists():
        shutil.rmtree(test_notebooks_dir)


@pytest.fixture(scope="session")
def jupyter_server():
    """Session-scoped Jupyter server that stays warm throughout all tests."""
    server_url, server_process, test_notebooks_dir = _start_jupyter_server(
        SERVER_PORT, "test_notebooks_session", "session "
    )

    yield server_url

    _cleanup_jupyter_server(server_process, test_notebooks_dir, "session ")


@pytest.fixture
def test_notebook(jupyter_server):
    """Create a test notebook with some initial cells for testing."""
    try:
        from mcp_jupyter.server import setup_notebook
    except ImportError:
        pytest.skip("mcp_jupyter package not available")

    notebook_name = "test_tools_notebook"

    # Create an empty notebook
    result = setup_notebook(notebook_name, server_url=jupyter_server)

    # Add initial cells using modify_notebook_cells
    from mcp_jupyter.server import modify_notebook_cells

    modify_notebook_cells(
        notebook_name, "add_code", "# Initial cell\nprint('Hello from initial cell')"
    )

    modify_notebook_cells(
        notebook_name,
        "add_code",
        "def add(a, b):\n    return a + b\n\nprint(add(2, 3))",
    )

    # Small delay to ensure notebook is fully saved and available
    time.sleep(0.2)

    yield f"{notebook_name}.ipynb"

    # Cleanup: delete the test notebook after test
    try:
        response = requests.delete(
            f"{jupyter_server}/api/contents/{notebook_name}.ipynb",
            headers={"Authorization": f"token {TOKEN}"},
        )
        # Reset notebook state after deletion
        try:
            from mcp_jupyter.server import NotebookState

            NotebookState.contents_hash = ""
        except ImportError:
            pass  # State management not available
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture(scope="session")
def llm_jupyter_server():
    """Session-scoped Jupyter server for LLM tests that stays warm throughout all tests."""
    server_url, server_process, test_notebooks_dir = _start_jupyter_server(
        LLM_SERVER_PORT, "test_notebooks_llm", "LLM "
    )

    yield server_url

    _cleanup_jupyter_server(server_process, test_notebooks_dir, "LLM ")
