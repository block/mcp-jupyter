"""Shared test configuration with single warm server for session reuse."""

import asyncio
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

import mcp_jupyter.server

# Fixtures for MCP Jupyter integration tests

# Constants
SERVER_PORT = 9999
TOKEN = "BLOCK"

# LLM test constants
LLM_SERVER_PORT = 10000


async def _check_server_health(server_url: str, token: str) -> bool:
    """Check if Jupyter server is healthy using asyncio."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("localhost", int(server_url.split(":")[-1])),
            timeout=1.0,
        )

        request = f"GET /api/sessions HTTP/1.1\r\nHost: localhost\r\nAuthorization: token {token}\r\nConnection: close\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()

        response = await asyncio.wait_for(reader.read(1024), timeout=1.0)
        writer.close()
        await writer.wait_closed()

        return b"200 OK" in response

    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False


async def _delete_notebook(server_url: str, notebook_name: str, token: str) -> bool:
    """Delete a notebook using asyncio."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("localhost", int(server_url.split(":")[-1])),
            timeout=2.0,
        )

        request = f"DELETE /api/contents/{notebook_name} HTTP/1.1\r\nHost: localhost\r\nAuthorization: token {token}\r\nConnection: close\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()

        response = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        writer.close()
        await writer.wait_closed()

        return b"200 " in response or b"204 " in response

    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False


def _start_jupyter_server(port: int, test_dir_name: str, server_type: str = ""):
    """Start a Jupyter server with given configuration."""
    test_notebooks_dir = Path(test_dir_name)
    server_url = f"http://localhost:{port}"

    if test_notebooks_dir.exists():
        shutil.rmtree(test_notebooks_dir)

    test_notebooks_dir.mkdir(exist_ok=True)

    jupyter_cmd = [
        "uv",
        "run",
        "jupyter",
        "lab",
        f"--port={port}",
        f"--IdentityProvider.token={TOKEN}",
        "--ip=0.0.0.0",
        "--no-browser",
        "--ServerApp.disable_check_xsrf=True",
        "--ServerApp.allow_origin='*'",
        "--LabServerApp.open_browser=False",
        f"--ServerApp.root_dir={test_notebooks_dir.absolute()}",
    ]

    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            jupyter_cmd.append("--allow-root")
    except (AttributeError, OSError):
        jupyter_cmd.append("--allow-root")

    print(f"Starting {server_type}Jupyter server on port {port}...")
    server_process = subprocess.Popen(
        jupyter_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid,
    )

    max_retries = 30
    retry_interval = 0.25
    initial_wait = 0.5

    time.sleep(initial_wait)

    for attempt in range(max_retries):
        try:
            is_healthy = asyncio.run(_check_server_health(server_url, TOKEN))
            if is_healthy:
                print(
                    f"{server_type}Jupyter server started successfully (attempt {attempt + 1})"
                )
                break
        except Exception:
            pass
        time.sleep(retry_interval)
        if attempt % 8 == 0:
            print(
                f"Waiting for {server_type.lower()}server to start... (attempt {attempt + 1}/{max_retries})"
            )
    else:
        try:
            os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        stdout, stderr = server_process.communicate()
        print(f"{server_type}Jupyter server stdout: {stdout}")
        print(f"{server_type}Jupyter server stderr: {stderr}")
        pytest.fail(f"{server_type}Jupyter server failed to start in time")

    # Reset notebook state at session start
    try:
        from mcp_jupyter.server import NotebookState

        NotebookState._contents_hashes = {}
        NotebookState.notebook_server_urls = {}
    except ImportError:
        print("Warning: Could not import NotebookState, state management disabled")

    return server_url, server_process, test_notebooks_dir


def _cleanup_jupyter_server(
    server_process, test_notebooks_dir: Path, server_type: str = ""
):
    """Clean up a Jupyter server and its test directory."""
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

    # Clean up all kernel connections from the per-notebook registry
    try:
        for path, kernel in list(mcp_jupyter.server._kernel_registry.items()):
            try:
                print(f"Cleaning up kernel connection for {path}...")
                kernel.stop()
            except Exception as e:
                print(f"Error cleaning up kernel for {path}: {e}")
        mcp_jupyter.server._kernel_registry.clear()
        mcp_jupyter.server._kernel_meta.clear()
    except Exception as e:
        print(f"Error cleaning up kernels: {e}")

    _cleanup_jupyter_server(server_process, test_notebooks_dir, "session ")


@pytest.fixture
async def test_notebook(jupyter_server):
    """Create a test notebook with some initial cells for testing."""
    try:
        from mcp_jupyter.server import setup_notebook
    except ImportError:
        pytest.skip("mcp_jupyter package not available")

    notebook_name = "test_tools_notebook"

    result = await setup_notebook(notebook_name, server_url=jupyter_server)

    from mcp_jupyter.server import modify_notebook_cells

    await modify_notebook_cells(
        notebook_name, "add_code", "# Initial cell\nprint('Hello from initial cell')"
    )

    await modify_notebook_cells(
        notebook_name,
        "add_code",
        "def add(a, b):\n    return a + b\n\nprint(add(2, 3))",
    )

    # Small delay to ensure notebook is fully saved and available
    await asyncio.sleep(0.2)

    yield f"{notebook_name}.ipynb"

    # Cleanup: delete the test notebook after test
    try:
        await _delete_notebook(jupyter_server, f"{notebook_name}.ipynb", TOKEN)
        try:
            from mcp_jupyter.server import NotebookState

            NotebookState._contents_hashes.pop(f"{notebook_name}.ipynb", None)
        except ImportError:
            pass
    except Exception:
        pass


@pytest.fixture(scope="session")
def llm_jupyter_server():
    """Session-scoped Jupyter server for LLM tests."""
    server_url, server_process, test_notebooks_dir = _start_jupyter_server(
        LLM_SERVER_PORT, "test_notebooks_llm", "LLM "
    )

    yield server_url

    _cleanup_jupyter_server(server_process, test_notebooks_dir, "LLM ")
