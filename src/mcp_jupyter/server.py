import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import time
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps
from typing import Optional, Union

import requests
from jupyter_kernel_client import KernelClient
from jupyter_nbmodel_client import NbModelClient, get_jupyter_notebook_websocket_url
from mcp.server.fastmcp import FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, ErrorData
from rich.console import Console
from rich.logging import RichHandler

from .notebook import list_notebook_sessions, prepare_notebook
from .state import NotebookState
from .utils import (
    TOKEN,
    _ensure_ipynb_extension,
    _extract_execution_count,
    extract_output,
)

# Initialize FastMCP server
mcp = FastMCP("notebook")


handlers = []
handlers.append(RichHandler(console=Console(stderr=True), rich_tracebacks=True))
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=handlers,
)

logger = logging.getLogger(__name__)

# Initialize kernel as None instead of connecting immediately
kernel: Optional[KernelClient] = None
# Add a dictionary to track kernel server URLs
kernel_server_urls = {}


def get_kernel_id(
    notebook_path: str, server_url: str = "http://localhost:8888"
) -> Optional[str]:
    """Get the kernel ID for the notebook from the user-provided Jupyter server.

    This ensures that the kernel used matches the state of the notebook
    as seen by the user on their running server.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        server_url: The server URL to use. Defaults to http://localhost:8888.


    Returns
    -------
        Optional[str]:
            - The kernel ID if found
            - None if no kernel is found but other notebooks exist
            - Will raise exception if no notebooks are running

    Raises
    ------
        McpError: If no active notebook sessions are found
        RequestException: If unable to connect to Jupyter server
    """
    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    response = requests.get(
        f"{server_url}/api/sessions", headers={"Authorization": f"token {TOKEN}"}
    )
    notebooks = response.json()

    # First, try to find kernel for the specified notebook
    kernel_ids = [
        notebook["kernel"]["id"]
        for notebook in notebooks
        if notebook["path"] == notebook_path
    ]

    if len(kernel_ids) == 1:
        return kernel_ids[0]

    # If not found, use the first available kernel and update notebook_path
    if notebooks:
        first_notebook = notebooks[0]
        first_notebook_path = first_notebook["path"]
        first_kernel_id = first_notebook["kernel"]["id"]

        logger.info(
            f"No kernel found for {notebook_path}, using notebook {first_notebook_path} instead"
        )
        logger.info(f"Using notebook path: {first_notebook_path}")

        return first_kernel_id

    # If no notebooks are running at all
    raise McpError(
        ErrorData(
            code=INTERNAL_ERROR,
            message=f"Failed to resolve kernel ID. No active notebook sessions found. Please open a notebook in Jupyter.",
        )
    )


def get_kernel(notebook_path: str, server_url: str = None) -> Optional[KernelClient]:
    """Get or initialize the kernel client connection to the user-provided server.

    Connects to an existing kernel associated with the notebook on the specified server.
    It assumes the Jupyter server is already running and accessible.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        server_url: The server URL to use. Defaults to None, which will use the URL stored
                   for this notebook if available, otherwise http://localhost:8888.

    Returns
    -------
        Optional[KernelClient]:
            - Existing kernel client if already initialized
            - New kernel client if successfully initialized
            - None if initialization fails

    Raises
    ------
        McpError: If the kernel client can't be initialized
        McpError: If there's an error connecting to the Jupyter server
    """
    global kernel, kernel_server_urls

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    # If server_url is not provided, use the stored one for this notebook
    if server_url is None:
        server_url = NotebookState.get_server_url(notebook_path)

    # Log server URL to confirm it's being passed correctly
    logger.info(f"Getting kernel with server_url={server_url}")

    # If kernel is already initialized, check if it's using the correct server_url
    if kernel is not None:
        # Use the kernel ID as a key in our dictionary
        kernel_id = kernel.kernel_id if hasattr(kernel, "kernel_id") else id(kernel)
        current_server_url = kernel_server_urls.get(kernel_id, "http://localhost:8888")

        # If server_url has changed, we need to create a new kernel
        if current_server_url != server_url:
            logger.info(
                f"Server URL changed from {current_server_url} to {server_url}, resetting kernel"
            )
            try:
                kernel.stop()  # Properly close the previous kernel
            except Exception as e:
                logger.warning(f"Error stopping kernel: {e}")
            kernel = None
            # Remove the old entry from our dictionary
            if kernel_id in kernel_server_urls:
                del kernel_server_urls[kernel_id]
        else:
            return kernel

    # Initialize the kernel
    try:
        logger.info(f"Initializing kernel client with server_url={server_url}")
        new_kernel = KernelClient(
            server_url=server_url,
            token=TOKEN,
            kernel_id=get_kernel_id(notebook_path, server_url),
        )

        new_kernel.start()
        kernel = new_kernel

        # Store the server_url in our dictionary using kernel ID as key
        kernel_id = (
            new_kernel.kernel_id if hasattr(new_kernel, "kernel_id") else id(new_kernel)
        )
        kernel_server_urls[kernel_id] = server_url

        return kernel
    except Exception as e:
        logger.warning(f"Failed to initialize kernel client: {e}")
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"Could not connect to Jupyter notebook server at {server_url}: {e}",
            )
        )


@contextmanager
def notebook_client(notebook_path: str, server_url: str = None):
    """Create and manage a Jupyter notebook client connection to the user-provided server.

    This context manager handles creating, starting and stopping the notebook client connection.
    It yields the notebook client that can be used to interact with the Jupyter notebook
    running on the user's server. It assumes the server is already running.

    Important note about paths:
    --------------------------
    The notebook_path parameter must be relative to the Jupyter server root directory,
    not an absolute path on the local filesystem.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        server_url: The server URL to use. Defaults to None, which will use the URL stored
                   for this notebook if available, otherwise http://localhost:8888.

    Yields
    ------
        NbModelClient: The notebook client instance that is connected to the Jupyter notebook.

    Raises
    ------
        WebSocketClosedError: If the websocket connection fails
        ConnectionError: If unable to connect to the Jupyter server
    """
    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    # If server_url is not provided, use the stored one for this notebook
    if server_url is None:
        server_url = NotebookState.get_server_url(notebook_path)

    logger.info(f"Creating notebook client with server_url={server_url}")

    try:
        notebook = NbModelClient(
            get_jupyter_notebook_websocket_url(
                server_url=server_url,
                token=TOKEN,
                path=notebook_path,
            )
        )
        notebook.start()
        yield notebook
    finally:
        notebook.stop()


@mcp.tool()
@NotebookState.state_dependent
def add_code_cell(notebook_path: str, cell_content: str, execute: bool = True) -> dict:
    """Add (and optionally execute) a code cell in a Jupyter notebook on the user-provided server.

    Default to execute=True unless the user requests otherwise or you have good reason
    not to execute immediately.

    If you are trying to fix a cell that previously threw an error,
    you should default to editing the cell vs adding a new one.

    Note that adding a cell without executing it leaves it with no execution_count which can make
    it slightly trickier to execute in a subsequent request, but goose can now find cells by
    cell_id and content as well, now that it can view the full notebook source.

    A motivating example for why this is state-dependent: user asks goose to write a function,
    user then manually modifies that function signature, then user asks goose to call that function
    in a new cell. If goose's knowledge is outdated, it will likely use the old signature.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        cell_content: Code content
        execute: Whether to execute the cell after adding it

    Returns
    -------
        dict
            Execution results containing
            (execution_count: int, outputs: list[dict], status: str)
            If execute=False, this will be an empty dict.

    Raises
    ------
        McpError: If there's an error connecting to the Jupyter server
    """
    logger.info("Adding code cell")

    results = {}
    with notebook_client(notebook_path) as notebook:
        position_index = notebook.add_code_cell(cell_content)

        # When the cell is added successfully but we don't need to execute it
        if not execute:
            return results

        # When we need to execute
        try:
            logger.info("Cell added successfully, now executing")
            results = execute_cell(notebook_path, position_index)
            return results
        except Exception as e:
            logger.error(f"Error during execution: {e}")
            # Return partial results if we have them
            results = {
                "error": str(e),
                "message": "Cell was added but execution failed",
            }
            return results


@mcp.tool()
def get_position_index(
    notebook_path: str,
    execution_count: Optional[Union[str, int]] = None,
    cell_id: Optional[str] = None,
) -> int:
    """Get the index of a code cell in a Jupyter notebook on the user-provided server.

    Dev notes re choice to pass in execution_count:
    - another option is have user describe cell and/or have model infer it based on contents,
    but that's also risky and could be annoying to type out
    - another option is to modify the current/active cell, which I know we can get in
    jupyter extensions but couldn't easily get that working here.
    jupyter-ai-agents/jupyter_ai_agents repo seems to get the current_cell_index somehow but
    haven't yet pinned down where/how.
    - considered mapping to cell_id (str) instead of positional index as the unique identifier,
    I think that would make goose less likely to confuse the two and lets us avoid the annoying
    formatting issues with square brackets/parentheses. But NBModelClient uses positional index to
    get/set cell values, so using ID here makes this clunkier.
    jupyter_nbmodel_client.agent.BaseNbAgent.get_cell(cell_id)
    could be helpful here, either directly or as a reference implementation.

    Could consider making this tool state_dependent, but I think it's mostly safe because it's
    typically used in service of other state-dependent operations like add/edit_code_cell.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        execution_count: The index (execution_count) that is visible to the user in the notebook UI.
            Formatted like "(19)" (a string starting and ending with parentheses, not including
            quotes). You must provide exactly one of (execution_count, cell_id).
        cell_id: A random str of characters like "205658d6-093c-4722-854c-90b149f254ad" that
            uniquely identifies a cell. These are not visible to the user but goose can find them
            with its view_source tool. You must provide exactly one of (execution_count, cell_id).

    Returns
    -------
        int: positional index that NBModelClient uses under the hood

    Raises
    ------
        ValueError: If neither or both execution_count and cell_id are provided
        ValueError: If no matching cell is found or multiple matches are found
    """
    if execution_count is None and cell_id is None:
        raise ValueError(
            "Must provide either execution_count or cell_id (got neither)."
        )
    if execution_count is not None and cell_id is not None:
        raise ValueError("Must provide either execution_count or cell_id (got both).")

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    # Extract the int version.
    # In each case we set one of the two params to a placeholder value that the actual notebook
    # metadata never uses (don't use None because metadata does use that sometimes).
    if execution_count is not None:
        execution_count_int = _extract_execution_count(execution_count)
        cell_id = "[placeholder-id]"
    else:
        execution_count_int = -1

    with notebook_client(notebook_path) as notebook:
        position_indices = set()
        for i, cell in enumerate(notebook._doc.ycells):
            if (
                cell.get("execution_count") == execution_count_int
                or cell.get("id") == cell_id
            ):
                position_indices.add(i)

        if len(position_indices) != 1:
            raise ValueError(
                f"Could not resolve cell from execution_index={execution_count} and "
                f"cell_id={cell_id}. "
                f"Found {position_indices}. Make sure you're passing in a unique execution index "
                "OR a unique cell_id that exists in the notebook."
            )

        return position_indices.pop()


@mcp.tool()
@NotebookState.refreshes_state
def view_source(
    notebook_path: str,
    execution_count: Optional[Union[str, int]] = None,
    position_index: Optional[int] = None,
) -> Union[dict, list[dict]]:
    """View the source code of a Jupyter notebook (either single cell or all cells) from the
    user-provided server.

    We need to support passing in either the execution_count or the position_index because
    depending on the context, goose may know one but not the other. Its knowledge also changes
    over time, e.g. if it executes or adds cells these numbers can change.
    Goose can pass in either *one* of the two arguments to view a single cell, or neither to view
    all cells. It must NOT pass in both.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        execution_count: The execution count to look for. Can be an integer (3), string ("3"),
                        or parenthesized string ("(3)")
        position_index: The position index to look for

    Returns
    -------
        Union[dict, list[dict]]:
            - If viewing a single cell: dict containing cell contents and metadata
              (cell_type, execution_count, metadata, outputs, source)
            - If viewing all cells: list of dicts containing all cells' contents and metadata

    Raises
    ------
        ValueError: If both execution_count and position_index are provided
        McpError: If there's an error connecting to the Jupyter server
    """
    if execution_count is not None and position_index is not None:
        raise ValueError("Cannot provide both execution_count and position_index.")

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    if execution_count is None and position_index is None:
        logger.info("Viewing all cells")
        view_all = True
    else:
        view_all = False

    with notebook_client(notebook_path) as notebook:
        if view_all:
            return notebook._doc.ycells.to_py()

        if position_index is None:
            position_index = get_position_index(
                notebook_path, execution_count=execution_count
            )
        return notebook[position_index]


@mcp.tool()
@NotebookState.state_dependent
def edit_code_cell(
    notebook_path: str, position_index: int, cell_content: str, execute: bool = True
) -> dict:
    """Edit a code cell in a Jupyter notebook on the user-provided server.

    Default to execute=True unless the user requests otherwise or you have good reason not to
    execute immediately.

    Note that users can edit cell contents too, so if you are making assumptions about the
    position_index of the cell to edit based on chat history with the user, you should first
    make sure the notebook state matches your expected state using your view_source tool.
    If it does not match the expected state, you should then use your view_source tool to update
    your knowledge of the current cell contents.

    If you execute a cell and it fails and you want to debug it, you should default to editing
    the existing cell vs adding a new cell each time you want to execute code.

    A motivating example for why this is state-dependent: user asks goose to write a function,
    user then manually modifies the function, then asks goose to make additional changes to the
    function. If goose's knowledge is outdated, it will likely ignore the user's recent changes
    and modify the old version of the function, losing user work.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        position_index: positional index that NBModelClient uses under the hood.
        cell_content: New code content to write to the cell.
        execute: Whether to execute the cell after editing

    Returns
    -------
        dict: Execution results containing:
            - execution_count: int
            - outputs: list[dict]
            - status: str
            If execute=False, returns an empty dict

    Raises
    ------
        McpError: If notebook state has changed since last viewed
        McpError: If there's an error connecting to the Jupyter server
        IndexError: If position_index is out of range
    """
    logger.info("Editing code cell")

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    full_cell_contents = {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": cell_content,
    }

    results = {}

    with notebook_client(notebook_path) as notebook:
        # Update cell source code.
        notebook[position_index] = full_cell_contents
        if execute:
            results = execute_cell(notebook_path, position_index)

    return results


@mcp.tool()
@NotebookState.refreshes_state
def execute_cell(notebook_path: str, position_index: int) -> dict:
    """Execute an existing code cell in a Jupyter notebook on the user-provided server.

    In most cases you should call add_code_cell or edit_code_cell instead, but occasionally
    you might want to re-execute a cell after changing a *different* cell.

    Note that users can edit cell contents too, so if you assume you know the position_index
    of the cell to execute based on past chat history, you should first make sure the notebook state
    matches your expected state using your view_source tool. If it does not match the
    expected state, you should then use your view_source tool to update your knowledge of the
    current cell contents.

    Technically could be considered state_dependent, but it is usually called inside edit_code_cell
    or add_code_cell which area already state_dependent. Every hash update is slow because we have
    to wait for the notebook to save first so using refreshes_state instead saves 1.5s per call.
    Only risk is if user asks goose to execute a single cell and goose assumes it knows the
    position_index already, but usually it would be faster for the user to just execute the cell
    directly - this tool is mostly useful to allow goose to debug independently.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        position_index: positional index that NBModelClient uses under the hood

    Returns
    -------
        dict: Execution results containing:
            - execution_count: int
            - outputs: list[dict] of output content
            - status: str indicating execution status ("ok" or "error")

    Raises
    ------
        McpError: If there's an error connecting to the Jupyter server
        IndexError: If position_index is out of range
        RuntimeError: If kernel execution fails
    """
    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    # Get kernel using the stored server URL
    kernel = get_kernel(notebook_path)

    with notebook_client(notebook_path) as notebook:
        return notebook.execute_cell(position_index, kernel)


@mcp.tool()
@NotebookState.state_dependent
def delete_cell(notebook_path: str, position_index: int) -> dict:
    """Delete a code cell in a Jupyter notebook on the user-provided server.

    Note that users can edit cell contents too, so if you assume you know the position_index
    of the cell to delete based on past chat history, you should first make sure the notebook state
    matches your expected state using your view_source tool. If it does not match the
    expected state, you should then use your view_source tool to update your knowledge of the
    current cell contents.

    A motivating example for why this is state-dependent: user asks goose to add a new cell,
    then user runs a few cells manually (changing execution_counts), then tells goose
    "now delete it". In the context of the conversation, this looks fine and Goose may assume it
    knows the correct position_index already, but its knowledge is outdated.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        position_index: positional index that NBModelClient uses under the hood

    Returns
    -------
        dict: Contains two keys:
            - "message": "Cell deleted" if successful, empty string if failed
            - "error": Error message if failed, empty string if successful

    Raises
    ------
        McpError: If notebook state has changed since last viewed
        IndexError: If position_index is out of range
    """
    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    results = {"message": "", "error": ""}
    with notebook_client(notebook_path) as notebook:
        # Found this interface as well but it fails currently, tries to call to_py() method
        # on a string. Maybe jupyter_nbmodel_client will fix this eventually.
        # For now we just copy the relevant portion of the delete operation (the part that fails
        # doesn't appear to be critical).
        # del notebook[position_index]
        try:
            with notebook._lock:
                notebook._doc.ycells.pop(position_index)
            results["message"] = "Cell deleted"
        except Exception as e:
            results["error"] = str(e)
    return results


@mcp.tool()
@NotebookState.refreshes_state
def add_markdown_cell(notebook_path: str, cell_content: str) -> dict:
    """Add a markdown cell in a Jupyter notebook on the user-provided server.

    Technically might be a little risky to mark this as refreshes_state because the user could make
    other changes that are invisible to goose. But trying it out this way because I don't think
    goose adding a markdown cell should necessarily force it to view the full notebook source on
    subsequent tool calls.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        cell_content: Markdown content

    Returns
    -------
        dict: Contains two keys:
            - "message": "Markdown cell added" if successful, empty string if failed
            - "error": Error message if failed, empty string if successful

    Raises
    ------
        McpError: If there's an error connecting to the Jupyter server
    """
    logger.info("Adding markdown cell")

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    results = {"message": "", "error": ""}
    try:
        with notebook_client(notebook_path) as notebook:
            notebook.add_markdown_cell(cell_content)
        results["message"] = "Markdown cell added"

    except Exception as e:
        logger.error(f"Error adding markdown cell: {e}")
        results["error"] = str(e)

    return results


@mcp.tool()
@NotebookState.refreshes_state
def install_packages(notebook_path: str, package_names: str) -> str:
    """Install one or more packages using uv pip in the notebook environment of the
    user-provided server.

    Unlike add_code_cell, this shouldn't rely on other code written in the notebook, so we mark
    it as refreshes_state rather than state_dependent. Assumes 'uv' is available in the
    environment where the Jupyter kernel is running.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        package_names: Space-separated list of package names to install

    Returns
    -------
        str: Installation result message including:
            - Success/failure status
            - Package names attempted to install
            - Installation output or error message

    Raises
    ------
        McpError: If there's an error connecting to the Jupyter server
        McpError: If kernel is not available
    """
    logger.info(f"Installing packages: {package_names}")

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    # Get kernel on demand - rely on NotebookState for server_url
    try:
        current_kernel = get_kernel(notebook_path)
    except McpError:
        # Just re-raise the error from get_kernel
        raise

    try:
        with notebook_client(notebook_path) as notebook:
            # Create a cell that installs the packages using uv pip
            cell_content = f"!uv pip install {package_names}"
            cell_index = notebook.add_code_cell(cell_content)
            result = notebook.execute_cell(cell_index, current_kernel)

            # Extract output to see if installation was successful
            outputs = result.get("outputs", [])
            if len(outputs) == 0:
                installation_result = "No output from installation command"
            else:
                installation_result = [extract_output(output) for output in outputs]

            return f"Installation of packages [{package_names}]: {installation_result}"

    except Exception as e:
        logger.error(f"Error installing packages: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
def check_jupyter_server(server_url: str = "http://localhost:8888") -> str:
    """Check if the user-provided Jupyter server is running and accessible.

    Args:
        server_url: The server URL to check. Defaults to http://localhost:8888.

    Returns
    -------
        str: Status message, either:
            - "Jupyter server is running" if server is accessible
            - "Jupyter server is not accessible" if server cannot be reached

    Raises
    ------
        None: This function handles all exceptions internally
    """
    try:
        response = requests.get(
            f"{server_url}/api/sessions", headers={"Authorization": f"token {TOKEN}"}
        )
        response.raise_for_status()
        return "Jupyter server is running"
    except Exception:
        return "Jupyter server is not accessible"


@mcp.tool()
@NotebookState.refreshes_state
def notebook(notebook_path: str, cells: list = None, server_url: str = None) -> dict:
    """Prepare notebook for use and connect to the kernel on the user-provided server.
    Will create a new Jupyter notebook if needed on the server.

    This tool assumes a Jupyter server is already running and accessible at the specified
    `server_url`. It connects to this existing server to manage the notebook.

    Note that notebook_path must be relative to the Jupyter server root, not an absolute
    filesystem path.

    Args:
        notebook_path: Path to the notebook, relative to the Jupyter server root.
        cells: Optional list of initial cell contents for a new notebook.
        server_url: Optional Jupyter server URL (default: http://localhost:8888). This URL
                    will be stored and used for subsequent interactions with this notebook.

    Returns
    -------
        dict: Information about the notebook and status message.
    """
    global kernel

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    # Only set the server URL if a non-None value is provided
    if server_url is not None:
        NotebookState.set_server_url(notebook_path, server_url)
    # Make sure we have a valid server_url for the rest of this function
    server_url = NotebookState.get_server_url(notebook_path)

    # Use the notebook module but with the local TOKEN
    from .notebook import prepare_notebook

    info = prepare_notebook(notebook_path, cells, server_url, TOKEN)

    # Refresh the state hash
    time.sleep(0.5)  # Short delay to ensure notebook is fully saved
    NotebookState.update_hash(notebook_path, server_url, caller="notebook_final")

    return info


@mcp.tool()
def list_sessions(server_url: str = None) -> list:
    """List all notebook sessions on the Jupyter server.

    Args:
        server_url: Optional Jupyter server URL (default: http://localhost:8888)

    Returns
    -------
        list: List of notebook sessions

    Raises
    ------
        McpError: If there's an error listing notebook sessions
    """
    # Use default server_url if not provided
    if server_url is None:
        server_url = "http://localhost:8888"

    return list_notebook_sessions(server_url, TOKEN)


if __name__ == "__main__":
    # Initialize and run the server
    logger.info("Starting MCP notebook server")
    mcp.run(transport="stdio")
