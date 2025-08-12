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
def query_notebook(
    notebook_path: str,
    query_type: str,
    execution_count: int = None,
    position_index: int = None,
    cell_id: str = None,
    server_url: str = None,
) -> Union[dict, list, str, int]:
    """Query notebook information and metadata on the user-provided server.

    This consolidates all read-only operations into a single tool following MCP best practices.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        query_type: Type of query to perform. Options:
            - 'view_source': View source code of notebook (single cell or all cells)
            - 'check_server': Check if Jupyter server is running and accessible
            - 'list_sessions': List all notebook sessions on the server
            - 'get_position_index': Get the index of a code cell
        execution_count: (For view_source/get_position_index) The execution count to look for.
            IMPORTANT: This is the number shown in square brackets like [3] in Jupyter UI.
            Only available for executed code cells. Must be an integer (e.g., 3).
            COMMON MISTAKE: Don't confuse with position_index!
            - execution_count=3 finds the cell that was executed 3rd (shows [3] in Jupyter)
            - position_index=3 finds the 4th cell in the notebook (0-indexed position)
        position_index: (For view_source) The position index to look for.
            This is the cell's physical position in the notebook (0-indexed).
            Examples: first cell = 0, second cell = 1, third cell = 2, etc.
            Works for all cell types (code, markdown, raw). Must be an integer.
        cell_id: (For get_position_index) Cell ID like "205658d6-093c-4722-854c-90b149f254ad".
            This is a unique identifier for each cell, visible in notebook metadata.
        server_url: (For check_server/list_sessions) Server URL (default: http://localhost:8888)

    Returns
    -------
        Union[dict, list, str, int]:
            - view_source: dict (single cell) or list[dict] (all cells) with cell contents/metadata
            - check_server: str status message
            - list_sessions: list of notebook sessions
            - get_position_index: int positional index

    Examples
    --------
        # View all cells in notebook
        query_notebook("my_notebook.ipynb", "view_source")

        # View cell by execution count (the [3] shown in Jupyter UI)
        query_notebook("my_notebook.ipynb", "view_source", execution_count=3)

        # View cell by position (first cell=0, second=1, etc)
        query_notebook("my_notebook.ipynb", "view_source", position_index=0)

        # Get position index of cell with execution count [5]
        query_notebook("my_notebook.ipynb", "get_position_index", execution_count=5)

        # Get position index by cell ID
        query_notebook("my_notebook.ipynb", "get_position_index", cell_id="205658d6-093c-4722-854c-90b149f254ad")

    Raises
    ------
        ValueError: If invalid query_type or missing required parameters
        McpError: If there's an error connecting to the Jupyter server
    """
    if query_type == "view_source":
        return _query_view_source(notebook_path, execution_count, position_index)
    elif query_type == "check_server":
        return _query_check_server(server_url or "http://localhost:8888")
    elif query_type == "list_sessions":
        return _query_list_sessions(server_url or "http://localhost:8888")
    elif query_type == "get_position_index":
        return _query_get_position_index(notebook_path, execution_count, cell_id)
    else:
        raise ValueError(
            f"Invalid query_type: {query_type}. Must be one of: view_source, check_server, list_sessions, get_position_index"
        )


@NotebookState.refreshes_state
def _query_view_source(
    notebook_path: str,
    execution_count: int = None,
    position_index: int = None,
) -> Union[dict, list[dict]]:
    """View the source code of a Jupyter notebook (either single cell or all cells).

    We need to support passing in either the execution_count or the position_index because
    depending on the context, goose may know one but not the other. Its knowledge also changes
    over time, e.g. if it executes or adds cells these numbers can change.
    Goose can pass in either *one* of the two arguments to view a single cell, or neither to view
    all cells. It must NOT pass in both.
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
            position_index = _query_get_position_index(
                notebook_path, execution_count=execution_count
            )
        return notebook[position_index]


def _query_check_server(server_url: str) -> str:
    """Check if the user-provided Jupyter server is running and accessible."""
    try:
        response = requests.get(
            f"{server_url}/api/sessions", headers={"Authorization": f"token {TOKEN}"}
        )
        response.raise_for_status()
        return "Jupyter server is running"
    except Exception:
        return "Jupyter server is not accessible"


def _query_list_sessions(server_url: str) -> list:
    """List all notebook sessions on the Jupyter server."""
    return list_notebook_sessions(server_url, TOKEN)


def _get_available_execution_counts(notebook_path: str) -> dict:
    """Get comprehensive cell information for better error messages.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.

    Returns
    -------
        dict: Contains:
            - execution_counts: list of actual execution counts (excluding None)
            - position_indices: list of all position indices
            - cell_types: list of cell types for each position
            - total_cells: total number of cells
            - code_cells: number of code cells
            - unexecuted_cells: number of code cells without execution count
    """
    notebook_path = _ensure_ipynb_extension(notebook_path)

    with notebook_client(notebook_path) as notebook:
        cells_info = {
            "execution_counts": [],
            "position_indices": [],
            "cell_types": [],
            "total_cells": 0,
            "code_cells": 0,
            "unexecuted_cells": 0,
        }

        for i, cell in enumerate(notebook._doc.ycells):
            cells_info["position_indices"].append(i)
            cell_type = cell.get("cell_type", "unknown")
            cells_info["cell_types"].append(cell_type)
            cells_info["total_cells"] += 1

            if cell_type == "code":
                cells_info["code_cells"] += 1
                execution_count = cell.get("execution_count")
                if execution_count is not None:
                    cells_info["execution_counts"].append(execution_count)
                else:
                    cells_info["unexecuted_cells"] += 1

        # Sort execution counts for better presentation
        cells_info["execution_counts"].sort()
        return cells_info


def _query_get_position_index(
    notebook_path: str,
    execution_count: int = None,
    cell_id: str = None,
) -> int:
    """Get the index of a code cell in a Jupyter notebook.

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
    """
    if execution_count is None and cell_id is None:
        raise ValueError(
            "Must provide either execution_count or cell_id (got neither)."
        )
    if execution_count is not None and cell_id is not None:
        raise ValueError("Must provide either execution_count or cell_id (got both).")

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    # Add parameter validation and user guidance
    if execution_count is not None:
        # Validate execution_count range
        if execution_count < 1:
            raise ValueError(
                f"execution_count={execution_count} is invalid. Execution counts start from 1. "
                "If you meant to use position_index (which starts from 0), use position_index parameter instead."
            )
        elif execution_count > 10000:  # Reasonable upper bound
            raise ValueError(
                f"execution_count={execution_count} seems unreasonably high. "
                "Are you sure this is correct? Most notebooks have execution counts in the 1-100 range. "
                "If you meant to use position_index, use position_index parameter instead."
            )
        execution_count_int = execution_count

    # Set placeholder values for the search
    # In each case we set one of the two params to a placeholder value that the actual notebook
    # metadata never uses (don't use None because metadata does use that sometimes).
    if execution_count is not None:
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
            # Get comprehensive cell information for better error message
            cells_info = _get_available_execution_counts(notebook_path)

            if len(position_indices) == 0:
                # No matching cells found
                error_parts = []
                if execution_count is not None:
                    error_parts.append(
                        f"No cell found with execution_count={execution_count}"
                    )
                    if cells_info["execution_counts"]:
                        available_counts = ", ".join(
                            map(str, cells_info["execution_counts"])
                        )
                        error_parts.append(
                            f"Available execution_counts: [{available_counts}]"
                        )
                    else:
                        error_parts.append(
                            "No cells have been executed yet (all execution_counts are None)"
                        )

                    # Suggest alternatives
                    error_parts.append(
                        f"Notebook has {cells_info['total_cells']} total cells (positions 0-{cells_info['total_cells'] - 1})"
                    )
                    if cells_info["code_cells"] > 0:
                        error_parts.append(
                            f"Including {cells_info['code_cells']} code cells"
                        )
                    if cells_info["unexecuted_cells"] > 0:
                        error_parts.append(
                            f"with {cells_info['unexecuted_cells']} unexecuted"
                        )

                    error_parts.append(
                        "Try using position_index instead, or execute the cell first to get an execution_count"
                    )

                if cell_id is not None and cell_id != "[placeholder-id]":
                    error_parts.append(f"No cell found with cell_id={cell_id}")

                error_message = ". ".join(error_parts)
            else:
                # Multiple matching cells found (should be rare)
                error_message = f"Found {len(position_indices)} cells matching the criteria at positions {sorted(position_indices)}."

            raise ValueError(error_message)

        return position_indices.pop()


@mcp.tool()
@NotebookState.state_dependent
def modify_notebook_cells(
    notebook_path: str,
    operation: str,
    cell_content: str = None,
    position_index: int = None,
    execute: bool = True,
) -> dict:
    """Modify notebook cells (add, edit, delete) on the user-provided server.

    This consolidates all cell modification operations into a single tool following MCP best practices.
    Default to execute=True unless the user requests otherwise or you have good reason not to
    execute immediately.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        operation: Type of cell operation. Options:
            - 'add_code': Add (and optionally execute) a code cell at end or specific position
            - 'edit_code': Edit a code cell at specific position
            - 'add_markdown': Add a markdown cell at end or specific position
            - 'edit_markdown': Edit an existing markdown cell at specific position
            - 'delete': Delete a cell at specific position
        cell_content: Content for the cell (required for add_code, edit_code, add_markdown, edit_markdown)
        position_index: Position index (0-indexed cell location) for operations. Must be an integer.
            - Optional for add_code/add_markdown: if provided, inserts at that position; if not, adds at end
            - Required for edit_code/edit_markdown/delete: specifies which cell to modify
            Examples: position_index=0 (first cell), position_index=2 (third cell)
        execute: Whether to execute code cells after adding/editing (default: True)

    Returns
    -------
        dict: Operation results containing:
            - For add_code/edit_code with execute=True: execution_count, outputs, status
            - For add_code/edit_code with execute=False: empty dict
            - For add_markdown/edit_markdown: message and error fields
            - For delete: message and error fields

    Raises
    ------
        ValueError: If invalid operation or missing required parameters
        McpError: If there's an error connecting to the Jupyter server
        IndexError: If position_index is out of range
    """
    if operation == "add_code":
        return _modify_add_code_cell(
            notebook_path, cell_content, execute, position_index
        )
    elif operation == "edit_code":
        return _modify_edit_code_cell(
            notebook_path, position_index, cell_content, execute
        )
    elif operation == "add_markdown":
        return _modify_add_markdown_cell(notebook_path, cell_content, position_index)
    elif operation == "edit_markdown":
        return _modify_edit_markdown_cell(notebook_path, position_index, cell_content)
    elif operation == "delete":
        return _modify_delete_cell(notebook_path, position_index)
    else:
        raise ValueError(
            f"Invalid operation: {operation}. Must be one of: add_code, edit_code, add_markdown, edit_markdown, delete"
        )


def _modify_add_code_cell(
    notebook_path: str,
    cell_content: str,
    execute: bool = True,
    position_index: int = None,
) -> dict:
    """Add (and optionally execute) a code cell in a Jupyter notebook.

    If you are trying to fix a cell that previously threw an error,
    you should default to editing the cell vs adding a new one.

    Note that adding a cell without executing it leaves it with no execution_count which can make
    it slightly trickier to execute in a subsequent request, but goose can now find cells by
    cell_id and content as well, now that it can view the full notebook source.

    A motivating example for why this is state-dependent: user asks goose to write a function,
    user then manually modifies that function signature, then user asks goose to call that function
    in a new cell. If goose's knowledge is outdated, it will likely use the old signature.
    """
    if not cell_content:
        raise ValueError("cell_content is required for add_code operation")

    logger.info("Adding code cell")

    results = {}
    with notebook_client(notebook_path) as notebook:
        if position_index is not None:
            # Insert at specific position
            notebook.insert_code_cell(position_index, cell_content)
            # position_index is already set to the desired position
        else:
            # Add at the end (original behavior)
            position_index = notebook.add_code_cell(cell_content)

        # When the cell is added successfully but we don't need to execute it
        if not execute:
            return results

        # When we need to execute
        try:
            logger.info("Cell added successfully, now executing")
            results = _execute_cell_internal(notebook_path, position_index)
            return results
        except Exception as e:
            logger.error(f"Error during execution: {e}")
            # Return partial results if we have them
            results = {
                "error": str(e),
                "message": "Cell was added but execution failed",
            }
            return results


def _modify_edit_code_cell(
    notebook_path: str, position_index: int, cell_content: str, execute: bool = True
) -> dict:
    """Edit a code cell in a Jupyter notebook.

    Note that users can edit cell contents too, so if you are making assumptions about the
    position_index of the cell to edit based on chat history with the user, you should first
    make sure the notebook state matches your expected state using your query_notebook tool.
    If it does not match the expected state, you should then use your query_notebook tool to update
    your knowledge of the current cell contents.

    If you execute a cell and it fails and you want to debug it, you should default to editing
    the existing cell vs adding a new cell each time you want to execute code.

    A motivating example for why this is state-dependent: user asks goose to write a function,
    user then manually modifies the function, then asks goose to make additional changes to the
    function. If goose's knowledge is outdated, it will likely ignore the user's recent changes
    and modify the old version of the function, losing user work.
    """
    if not cell_content:
        raise ValueError("cell_content is required for edit_code operation")
    if position_index is None:
        raise ValueError("position_index is required for edit_code operation")

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
            results = _execute_cell_internal(notebook_path, position_index)

    return results


def _modify_add_markdown_cell(
    notebook_path: str, cell_content: str, position_index: Optional[int] = None
) -> dict:
    """Add a markdown cell in a Jupyter notebook.

    Technically might be a little risky to mark this as refreshes_state because the user could make
    other changes that are invisible to goose. But trying it out this way because I don't think
    goose adding a markdown cell should necessarily force it to view the full notebook source on
    subsequent tool calls.
    """
    if not cell_content:
        raise ValueError("cell_content is required for add_markdown operation")

    logger.info("Adding markdown cell")

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    results = {"message": "", "error": ""}
    try:
        with notebook_client(notebook_path) as notebook:
            if position_index is not None:
                # Insert at specific position
                notebook.insert_markdown_cell(position_index, cell_content)
                results["message"] = (
                    f"Markdown cell inserted at position {position_index}"
                )
            else:
                # Add at the end (original behavior)
                notebook.add_markdown_cell(cell_content)
                results["message"] = "Markdown cell added"

    except Exception as e:
        logger.error(f"Error adding markdown cell: {e}")
        results["error"] = str(e)

    return results


def _modify_edit_markdown_cell(
    notebook_path: str, position_index: int, cell_content: str
) -> dict:
    """Edit an existing markdown cell in a Jupyter notebook.

    Note that users can edit cell contents too, so if you are making assumptions about the
    position_index of the cell to edit based on chat history with the user, you should first
    make sure the notebook state matches your expected state using your query_notebook tool.
    If it does not match the expected state, you should then use your query_notebook tool to update
    your knowledge of the current cell contents.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        position_index: positional index that NBModelClient uses under the hood.
        cell_content: New markdown content to write to the cell.

    Returns
    -------
        dict: Contains two keys:
            - "message": "Markdown cell edited" if successful, empty string if failed
            - "error": Error message if failed, empty string if successful

    Raises
    ------
        McpError: If notebook state has changed since last viewed
        McpError: If there's an error connecting to the Jupyter server
        IndexError: If position_index is out of range
    """
    if not cell_content:
        raise ValueError("cell_content is required for edit_markdown operation")
    if position_index is None:
        raise ValueError("position_index is required for edit_markdown operation")

    logger.info("Editing markdown cell")

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    full_cell_contents = {
        "cell_type": "markdown",
        "metadata": {},
        "source": cell_content,
    }

    results = {"message": "", "error": ""}

    try:
        with notebook_client(notebook_path) as notebook:
            # Update cell source code.
            notebook[position_index] = full_cell_contents
        results["message"] = "Markdown cell edited"
    except Exception as e:
        logger.error(f"Error editing markdown cell: {e}")
        results["error"] = str(e)

    return results


def _modify_delete_cell(notebook_path: str, position_index: int) -> dict:
    """Delete a code cell in a Jupyter notebook.

    Note that users can edit cell contents too, so if you assume you know the position_index
    of the cell to delete based on past chat history, you should first make sure the notebook state
    matches your expected state using your query_notebook tool. If it does not match the
    expected state, you should then use your query_notebook tool to update your knowledge of the
    current cell contents.

    A motivating example for why this is state-dependent: user asks goose to add a new cell,
    then user runs a few cells manually (changing execution_counts), then tells goose
    "now delete it". In the context of the conversation, this looks fine and Goose may assume it
    knows the correct position_index already, but its knowledge is outdated.
    """
    if position_index is None:
        raise ValueError("position_index is required for delete operation")

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
def execute_notebook_code(
    notebook_path: str,
    execution_type: str,
    position_index: int = None,
    package_names: str = None,
) -> Union[dict, str]:
    """Execute code in a Jupyter notebook on the user-provided server.

    This consolidates all code execution operations into a single tool following MCP best practices.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        execution_type: Type of execution operation. Options:
            - 'execute_cell': Execute an existing code cell
            - 'install_packages': Install packages using uv pip in the notebook environment
        position_index: (For execute_cell) Positional index of cell to execute
        package_names: (For install_packages) Space-separated list of package names to install

    Returns
    -------
        Union[dict, str]:
            - execute_cell: dict with execution_count, outputs, status
            - install_packages: str with installation result message

    Raises
    ------
        ValueError: If invalid execution_type or missing required parameters
        McpError: If there's an error connecting to the Jupyter server
        IndexError: If position_index is out of range
        RuntimeError: If kernel execution fails
    """
    if execution_type == "execute_cell":
        return _execute_cell_internal(notebook_path, position_index)
    elif execution_type == "install_packages":
        return _execute_install_packages(notebook_path, package_names)
    else:
        raise ValueError(
            f"Invalid execution_type: {execution_type}. Must be one of: execute_cell, install_packages"
        )


def _execute_cell_internal(notebook_path: str, position_index: int) -> dict:
    """Execute an existing code cell in a Jupyter notebook.

    In most cases you should call modify_notebook_cells instead, but occasionally
    you might want to re-execute a cell after changing a *different* cell.

    Note that users can edit cell contents too, so if you assume you know the position_index
    of the cell to execute based on past chat history, you should first make sure the notebook state
    matches your expected state using your query_notebook tool. If it does not match the
    expected state, you should then use your query_notebook tool to update your knowledge of the
    current cell contents.

    Technically could be considered state_dependent, but it is usually called inside edit_code_cell
    or add_code_cell which area already state_dependent. Every hash update is slow because we have
    to wait for the notebook to save first so using refreshes_state instead saves 1.5s per call.
    Only risk is if user asks goose to execute a single cell and goose assumes it knows the
    position_index already, but usually it would be faster for the user to just execute the cell
    directly - this tool is mostly useful to allow goose to debug independently.
    """
    if position_index is None:
        raise ValueError("position_index is required for execute_cell operation")

    # Ensure the notebook path has the .ipynb extension
    notebook_path = _ensure_ipynb_extension(notebook_path)

    # Get kernel using the stored server URL
    kernel = get_kernel(notebook_path)

    with notebook_client(notebook_path) as notebook:
        return notebook.execute_cell(position_index, kernel)


def _execute_install_packages(notebook_path: str, package_names: str) -> str:
    """Install one or more packages using uv pip in the notebook environment.

    Unlike add_code_cell, this shouldn't rely on other code written in the notebook, so we mark
    it as refreshes_state rather than state_dependent. Assumes 'uv' is available in the
    environment where the Jupyter kernel is running.
    """
    if not package_names:
        raise ValueError("package_names is required for install_packages operation")

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
@NotebookState.refreshes_state
def setup_notebook(
    notebook_path: str, cells: list = None, server_url: str = None
) -> dict:
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


if __name__ == "__main__":
    # Initialize and run the server
    logger.info("Starting MCP notebook server")
    mcp.run(transport="stdio")
