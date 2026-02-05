import functools
import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional, Union

import anyio
import httpx
from jupyter_kernel_client import KernelClient
from mcp.server.fastmcp import FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, ErrorData
from rich.console import Console
from rich.logging import RichHandler

from .notebook import list_notebook_sessions, prepare_notebook
from .rest_client import NotebookClient
from .state import NotebookState
from .utils import (
    TOKEN,
    _ensure_ipynb_extension,
    extract_output,
    filter_image_outputs,
    get_http_client,
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

# ── Per-notebook kernel registry (replaces global singleton) ──────────────────

_kernel_registry: dict[str, KernelClient] = {}
_kernel_meta: dict[str, str] = {}  # notebook_path → server_url

# ── Per-notebook locks ────────────────────────────────────────────────────────

_kernel_locks: dict[str, anyio.Lock] = {}
_registry_lock: Optional[anyio.Lock] = None


async def _get_notebook_lock(path: str) -> anyio.Lock:
    """Get or create a per-notebook lock. Uses a bootstrap lock for TOCTOU safety."""
    global _registry_lock
    if _registry_lock is None:
        _registry_lock = anyio.Lock()
    async with _registry_lock:
        if path not in _kernel_locks:
            _kernel_locks[path] = anyio.Lock()
        return _kernel_locks[path]


# ── Kernel management ─────────────────────────────────────────────────────────


async def get_kernel_id(
    notebook_path: str, server_url: str = "http://localhost:8888"
) -> Optional[str]:
    """Get the kernel ID for the notebook from the Jupyter server."""
    notebook_path = _ensure_ipynb_extension(notebook_path)

    client = get_http_client()
    response = await client.get(
        f"{server_url}/api/sessions",
        headers={"Authorization": f"token {TOKEN}"},
    )
    notebooks = response.json()

    kernel_ids = [
        notebook["kernel"]["id"]
        for notebook in notebooks
        if notebook["path"] == notebook_path
    ]

    if len(kernel_ids) == 1:
        return kernel_ids[0]

    if notebooks:
        first_notebook = notebooks[0]
        first_notebook_path = first_notebook["path"]
        first_kernel_id = first_notebook["kernel"]["id"]

        logger.info(
            f"No kernel found for {notebook_path}, using notebook {first_notebook_path} instead"
        )
        return first_kernel_id

    raise McpError(
        ErrorData(
            code=INTERNAL_ERROR,
            message="Failed to resolve kernel ID. No active notebook sessions found. "
            "Please open a notebook in Jupyter.",
        )
    )


async def get_kernel(
    notebook_path: str, server_url: str = None
) -> KernelClient:
    """Get or create a kernel client for a specific notebook.

    Each notebook gets its own KernelClient, stored in _kernel_registry.
    A per-notebook lock serializes kernel creation.
    """
    notebook_path = _ensure_ipynb_extension(notebook_path)

    if server_url is None:
        server_url = NotebookState.get_server_url(notebook_path)

    logger.info(f"Getting kernel for {notebook_path} with server_url={server_url}")

    lock = await _get_notebook_lock(notebook_path)
    async with lock:
        # Check if kernel exists and server_url matches
        if notebook_path in _kernel_registry:
            current_url = _kernel_meta.get(notebook_path, "http://localhost:8888")
            if current_url == server_url:
                return _kernel_registry[notebook_path]
            # Server URL changed — stop old kernel
            logger.info(
                f"Server URL changed from {current_url} to {server_url} "
                f"for {notebook_path}, resetting kernel"
            )
            old_kernel = _kernel_registry.pop(notebook_path)
            _kernel_meta.pop(notebook_path, None)
            try:
                await anyio.to_thread.run_sync(old_kernel.stop)
            except Exception as e:
                logger.warning(f"Error stopping kernel for {notebook_path}: {e}")

        # Create new kernel
        try:
            logger.info(f"Initializing kernel client for {notebook_path} at {server_url}")
            kernel_id = await get_kernel_id(notebook_path, server_url)
            new_kernel = KernelClient(
                server_url=server_url,
                token=TOKEN,
                kernel_id=kernel_id,
                client_kwargs={"reconnect_interval": 5},
            )
            await anyio.to_thread.run_sync(new_kernel.start)

            _kernel_registry[notebook_path] = new_kernel
            _kernel_meta[notebook_path] = server_url
            return new_kernel
        except Exception as e:
            logger.warning(f"Failed to initialize kernel client: {e}")
            raise McpError(
                ErrorData(
                    code=INTERNAL_ERROR,
                    message=f"Could not connect to Jupyter notebook server at {server_url}: {e}",
                )
            )


async def cleanup_all_kernels():
    """Stop all kernel clients. Call on server shutdown."""
    for path, kernel in list(_kernel_registry.items()):
        try:
            await anyio.to_thread.run_sync(kernel.stop)
        except Exception as e:
            logger.warning(f"Error stopping kernel for {path}: {e}")
    _kernel_registry.clear()
    _kernel_meta.clear()


# ── Notebook client context manager ──────────────────────────────────────────


@asynccontextmanager
async def notebook_client(notebook_path: str, server_url: str = None):
    """Async context manager for a NotebookClient connection."""
    notebook_path = _ensure_ipynb_extension(notebook_path)

    if server_url is None:
        server_url = NotebookState.get_server_url(notebook_path)

    logger.info(f"Creating notebook client with server_url={server_url}")

    notebook = NotebookClient(
        server_url=server_url, notebook_path=notebook_path, token=TOKEN
    )
    try:
        await notebook.connect()
        yield notebook
    finally:
        await notebook.disconnect()


# ── Tool: query_notebook ─────────────────────────────────────────────────────


@mcp.tool()
async def query_notebook(
    notebook_path: str,
    query_type: str,
    execution_count: int = None,
    position_index: int = None,
    cell_id: str = None,
    server_url: str = None,
    include_outputs: bool = True,
    source_preview_length: int = 60,
) -> Union[dict, list, str, int]:
    r"""Query notebook information and metadata on the user-provided server.

    This consolidates all read-only operations into a single tool following MCP best practices.

    IMPORTANT: Server URL Configuration
    ----------------------------------
    This tool requires a server URL to connect to your Jupyter server. You have two options:

    Option 1 - Call setup_notebook first (RECOMMENDED):
        setup_notebook("my_notebook", server_url="http://localhost:9999")
        query_notebook("my_notebook", "view_source")  # Uses stored URL automatically

    Option 2 - Pass server_url explicitly every time:
        query_notebook("my_notebook", "view_source", server_url="http://localhost:9999")

    If neither is done, it defaults to http://localhost:8888 which may not be correct.

    Args:
        notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                       relative to the Jupyter server root.
        query_type: Type of query to perform. Options:
            - 'view_source': View source code of notebook (single cell or all cells)
            - 'list_cells': Get compact cell metadata (position, type, preview) without full content
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
        server_url: Server URL to connect to. If not provided, uses the URL stored by setup_notebook,
                   or falls back to http://localhost:8888
        include_outputs: (For view_source) If True (default), include cell outputs.
            If False, strip all outputs to reduce token usage.
        source_preview_length: (For list_cells) Number of characters to include in source preview.
            Defaults to 60.

    Returns
    -------
        Union[dict, list, str, int]:
            - view_source: dict (single cell) or list[dict] (all cells) with cell contents/metadata
            - list_cells: list[dict] with compact metadata (position_index, cell_type, source_preview,
              source_len, execution_count, has_output)
            - check_server: str status message
            - list_sessions: list of notebook sessions
            - get_position_index: int positional index

    Examples
    --------
        # View all cells in notebook
        query_notebook("my_notebook.ipynb", "view_source")

        # View all cells without outputs (saves tokens)
        query_notebook("my_notebook.ipynb", "view_source", include_outputs=False)

        # Get compact cell listing (much smaller than view_source)
        query_notebook("my_notebook.ipynb", "list_cells")

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
        result = await _query_view_source(
            notebook_path, execution_count, position_index, server_url, include_outputs
        )
        await NotebookState.update_hash(notebook_path, server_url, caller="query_notebook")
        return result
    elif query_type == "list_cells":
        result = await _query_list_cells(notebook_path, server_url, source_preview_length)
        await NotebookState.update_hash(notebook_path, server_url, caller="query_notebook")
        return result
    elif query_type == "check_server":
        return await _query_check_server(server_url or "http://localhost:8888")
    elif query_type == "list_sessions":
        return await _query_list_sessions(server_url or "http://localhost:8888")
    elif query_type == "get_position_index":
        result = await _query_get_position_index(notebook_path, execution_count, cell_id)
        await NotebookState.update_hash(notebook_path, server_url, caller="query_notebook")
        return result
    else:
        raise ValueError(
            f"Invalid query_type: {query_type}. Must be one of: view_source, list_cells, "
            "check_server, list_sessions, get_position_index"
        )


# ── Output filtering helpers (pure functions, no change needed) ──────────────


def _filter_cell_outputs(cell_data: Union[dict, list[dict]]) -> Union[dict, list[dict]]:
    """Filter out verbose output data from cell data."""

    def filter_single_cell(cell: dict) -> dict:
        if not isinstance(cell, dict):
            return cell

        filtered_cell = {
            "cell_type": cell.get("cell_type"),
            "source": cell.get("source"),
            "metadata": cell.get("metadata", {}),
        }

        if cell.get("cell_type") == "code":
            filtered_cell["execution_count"] = cell.get("execution_count")

            if "outputs" in cell:
                filtered_outputs = []
                for output in cell["outputs"]:
                    if isinstance(output, dict):
                        filtered_output = {
                            "output_type": output.get("output_type"),
                        }

                        if "text" in output:
                            filtered_output["text"] = output["text"]
                        if "name" in output:
                            filtered_output["name"] = output["name"]

                        if "data" in output:
                            data_types = list(output["data"].keys())
                            if any(
                                "image" in dt or "png" in dt or "jpeg" in dt
                                for dt in data_types
                            ):
                                filtered_output["data"] = {
                                    "[filtered]": f"Image data present ({', '.join(data_types)})"
                                }
                            elif any("html" in dt for dt in data_types):
                                filtered_output["data"] = {
                                    "[filtered]": f"HTML data present ({', '.join(data_types)})"
                                }
                            else:
                                filtered_output["data"] = output["data"]

                        filtered_outputs.append(filtered_output)

                filtered_cell["outputs"] = filtered_outputs

        return filtered_cell

    if isinstance(cell_data, list):
        return [filter_single_cell(cell) for cell in cell_data]
    else:
        return filter_single_cell(cell_data)


def _strip_outputs(cell_data: Union[dict, list[dict]]) -> Union[dict, list[dict]]:
    """Remove all outputs from cell data."""

    def strip_single(cell: dict) -> dict:
        if not isinstance(cell, dict):
            return cell
        result = cell.copy()
        if result.get("cell_type") == "code":
            result["outputs"] = []
        return result

    if isinstance(cell_data, list):
        return [strip_single(c) for c in cell_data]
    return strip_single(cell_data)


# ── Query helpers ─────────────────────────────────────────────────────────────


async def _query_list_cells(
    notebook_path: str,
    server_url: str = None,
    source_preview_length: int = 60,
) -> list[dict]:
    """Return compact cell metadata without full content."""
    if source_preview_length < 1:
        source_preview_length = 60

    notebook_path = _ensure_ipynb_extension(notebook_path)

    async with notebook_client(notebook_path, server_url) as notebook:
        cells = []
        for i, cell in enumerate(notebook._doc.ycells):
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)

            cell_info = {
                "position_index": i,
                "cell_type": cell.get("cell_type", "unknown"),
                "source_preview": source[:source_preview_length].replace("\n", " "),
                "source_len": len(source),
            }

            if cell.get("cell_type") == "code":
                cell_info["execution_count"] = cell.get("execution_count")
                cell_info["has_output"] = bool(cell.get("outputs"))

            cells.append(cell_info)

        return cells


async def _query_view_source(
    notebook_path: str,
    execution_count: int = None,
    position_index: int = None,
    server_url: str = None,
    include_outputs: bool = True,
) -> Union[dict, list[dict]]:
    """View the source code of a Jupyter notebook."""
    if execution_count is not None and position_index is not None:
        raise ValueError("Cannot provide both execution_count and position_index.")

    notebook_path = _ensure_ipynb_extension(notebook_path)

    if execution_count is None and position_index is None:
        logger.info("Viewing all cells")
        view_all = True
    else:
        view_all = False

    async with notebook_client(notebook_path, server_url) as notebook:
        if view_all:
            raw_cells = notebook._doc.ycells.to_py()
            if not include_outputs:
                raw_cells = _strip_outputs(raw_cells)
            return _filter_cell_outputs(raw_cells)

        if position_index is None:
            position_indices = set()
            execution_count_int = execution_count if execution_count is not None else -1

            for i, cell in enumerate(notebook._doc.ycells):
                if cell.get("execution_count") == execution_count_int:
                    position_indices.add(i)

            if len(position_indices) != 1:
                cells_info = await _get_available_execution_counts(notebook_path)

                if len(position_indices) == 0:
                    error_parts = []
                    if execution_count is not None:
                        error_parts.append(f"execution count {execution_count}")

                    error_msg = f"No cells found with {' and '.join(error_parts)}."

                    if cells_info["execution_counts"]:
                        error_msg += (
                            f" Available execution counts: {cells_info['execution_counts']}"
                        )
                    else:
                        error_msg += " No cells have been executed yet."

                    raise ValueError(error_msg)
                else:
                    raise ValueError(
                        f"Multiple cells found with execution count {execution_count}"
                    )

            position_index = position_indices.pop()

        raw_cell = notebook[position_index]
        if not include_outputs:
            raw_cell = _strip_outputs(raw_cell)
        return _filter_cell_outputs(raw_cell)


async def _query_check_server(server_url: str) -> str:
    """Check if the Jupyter server is running."""
    try:
        client = get_http_client()
        response = await client.get(
            f"{server_url}/api/sessions",
            headers={"Authorization": f"token {TOKEN}"},
        )
        response.raise_for_status()
        return "Jupyter server is running"
    except httpx.TimeoutException:
        return "Jupyter server is not accessible (timeout)"
    except httpx.ConnectError:
        return "Jupyter server is not accessible (connection error)"
    except Exception:
        return "Jupyter server is not accessible"


async def _query_list_sessions(server_url: str) -> list:
    """List all notebook sessions on the Jupyter server."""
    return await list_notebook_sessions(server_url, TOKEN)


async def _get_available_execution_counts(notebook_path: str) -> dict:
    """Get comprehensive cell information for error messages."""
    notebook_path = _ensure_ipynb_extension(notebook_path)

    async with notebook_client(notebook_path) as notebook:
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

        cells_info["execution_counts"].sort()
        return cells_info


async def _query_get_position_index(
    notebook_path: str,
    execution_count: int = None,
    cell_id: str = None,
) -> int:
    """Get the index of a code cell in a Jupyter notebook."""
    if execution_count is None and cell_id is None:
        raise ValueError("Must provide either execution_count or cell_id (got neither).")
    if execution_count is not None and cell_id is not None:
        raise ValueError("Must provide either execution_count or cell_id (got both).")

    notebook_path = _ensure_ipynb_extension(notebook_path)

    if execution_count is not None:
        if execution_count < 1:
            raise ValueError(
                f"execution_count={execution_count} is invalid. Execution counts start from 1. "
                "If you meant to use position_index (which starts from 0), use position_index parameter instead."
            )
        elif execution_count > 10000:
            raise ValueError(
                f"execution_count={execution_count} seems unreasonably high. "
                "Are you sure this is correct? Most notebooks have execution counts in the 1-100 range. "
                "If you meant to use position_index, use position_index parameter instead."
            )
        execution_count_int = execution_count

    if execution_count is not None:
        cell_id = "[placeholder-id]"
    else:
        execution_count_int = -1

    async with notebook_client(notebook_path) as notebook:
        position_indices = set()
        for i, cell in enumerate(notebook._doc.ycells):
            if (
                cell.get("execution_count") == execution_count_int
                or cell.get("id") == cell_id
            ):
                position_indices.add(i)

        if len(position_indices) != 1:
            cells_info = await _get_available_execution_counts(notebook_path)

            if len(position_indices) == 0:
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

                    error_parts.append(
                        f"Notebook has {cells_info['total_cells']} total cells "
                        f"(positions 0-{cells_info['total_cells'] - 1})"
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
                        "Try using position_index instead, or execute the cell first "
                        "to get an execution_count"
                    )

                if cell_id is not None and cell_id != "[placeholder-id]":
                    error_parts.append(f"No cell found with cell_id={cell_id}")

                error_message = ". ".join(error_parts)
            else:
                error_message = (
                    f"Found {len(position_indices)} cells matching the criteria "
                    f"at positions {sorted(position_indices)}."
                )

            raise ValueError(error_message)

        return position_indices.pop()


# ── Tool: modify_notebook_cells ──────────────────────────────────────────────


@mcp.tool()
@NotebookState.state_dependent
async def modify_notebook_cells(
    notebook_path: str,
    operation: str,
    cell_content: str = None,
    position_index: int = None,
    execute: bool = True,
) -> dict:
    r"""Modify notebook cells (add, edit, delete) on the user-provided server.

    This consolidates all cell modification operations into a single tool following MCP best practices.
    Default to execute=True unless the user requests otherwise or you have good reason not to
    execute immediately.

    IMPORTANT: Server URL Configuration
    ----------------------------------
    This tool requires that you first call setup_notebook with the correct server URL:

    Required setup:
        setup_notebook(\"my_notebook\", server_url=\"http://localhost:9999\")

    Then you can use this tool:
        modify_notebook_cells(\"my_notebook\", \"add_code\", \"print('Hello')\")

    Without setup_notebook, this will try to connect to http://localhost:8888 by default.

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
        return await _modify_add_code_cell(
            notebook_path, cell_content, execute, position_index
        )
    elif operation == "edit_code":
        return await _modify_edit_code_cell(
            notebook_path, position_index, cell_content, execute
        )
    elif operation == "add_markdown":
        return await _modify_add_markdown_cell(notebook_path, cell_content, position_index)
    elif operation == "edit_markdown":
        return await _modify_edit_markdown_cell(notebook_path, position_index, cell_content)
    elif operation == "delete":
        return await _modify_delete_cell(notebook_path, position_index)
    else:
        raise ValueError(
            f"Invalid operation: {operation}. Must be one of: add_code, edit_code, "
            "add_markdown, edit_markdown, delete"
        )


# ── Modify helpers ────────────────────────────────────────────────────────────


async def _modify_add_code_cell(
    notebook_path: str,
    cell_content: str,
    execute: bool = True,
    position_index: int = None,
) -> dict:
    """Add (and optionally execute) a code cell in a Jupyter notebook."""
    if not cell_content:
        raise ValueError("cell_content is required for add_code operation")

    logger.info("Adding code cell")

    results = {}
    async with notebook_client(notebook_path) as notebook:
        if position_index is not None:
            await notebook.insert_code_cell(position_index, cell_content)
        else:
            position_index = await notebook.add_code_cell(cell_content)

        if not execute:
            return results

        try:
            logger.info("Cell added successfully, now executing")
            results = await _execute_cell_internal(notebook_path, position_index)
            return results
        except Exception as e:
            import traceback

            logger.error(f"Error during execution: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            results = {
                "error": str(e),
                "message": "Cell was added but execution failed",
                "traceback": traceback.format_exc(),
            }
            return results


async def _modify_edit_code_cell(
    notebook_path: str, position_index: int, cell_content: str, execute: bool = True
) -> dict:
    """Edit a code cell in a Jupyter notebook."""
    if not cell_content:
        raise ValueError("cell_content is required for edit_code operation")
    if position_index is None:
        raise ValueError("position_index is required for edit_code operation")

    logger.info("Editing code cell")

    notebook_path = _ensure_ipynb_extension(notebook_path)

    full_cell_contents = {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": cell_content,
    }

    results = {}

    async with notebook_client(notebook_path) as notebook:
        await notebook.set_cell(position_index, full_cell_contents)
        if execute:
            results = await _execute_cell_internal(notebook_path, position_index)

    return results


async def _modify_add_markdown_cell(
    notebook_path: str, cell_content: str, position_index: Optional[int] = None
) -> dict:
    """Add a markdown cell in a Jupyter notebook."""
    if not cell_content:
        raise ValueError("cell_content is required for add_markdown operation")

    logger.info("Adding markdown cell")

    notebook_path = _ensure_ipynb_extension(notebook_path)

    results = {"message": "", "error": ""}
    try:
        async with notebook_client(notebook_path) as notebook:
            if position_index is not None:
                await notebook.insert_markdown_cell(position_index, cell_content)
                results["message"] = (
                    f"Markdown cell inserted at position {position_index}"
                )
            else:
                await notebook.add_markdown_cell(cell_content)
                results["message"] = "Markdown cell added"

    except Exception as e:
        logger.error(f"Error adding markdown cell: {e}")
        results["error"] = str(e)

    return results


async def _modify_edit_markdown_cell(
    notebook_path: str, position_index: int, cell_content: str
) -> dict:
    """Edit an existing markdown cell in a Jupyter notebook."""
    if not cell_content:
        raise ValueError("cell_content is required for edit_markdown operation")
    if position_index is None:
        raise ValueError("position_index is required for edit_markdown operation")

    logger.info("Editing markdown cell")

    notebook_path = _ensure_ipynb_extension(notebook_path)

    full_cell_contents = {
        "cell_type": "markdown",
        "metadata": {},
        "source": cell_content,
    }

    results = {"message": "", "error": ""}

    try:
        async with notebook_client(notebook_path) as notebook:
            await notebook.set_cell(position_index, full_cell_contents)
        results["message"] = "Markdown cell edited"
    except Exception as e:
        logger.error(f"Error editing markdown cell: {e}")
        results["error"] = str(e)

    return results


async def _modify_delete_cell(notebook_path: str, position_index: int) -> dict:
    """Delete a cell in a Jupyter notebook."""
    if position_index is None:
        raise ValueError("position_index is required for delete operation")

    notebook_path = _ensure_ipynb_extension(notebook_path)

    results = {"message": "", "error": ""}
    async with notebook_client(notebook_path) as notebook:
        try:
            await notebook.delete_cell(position_index)
            results["message"] = "Cell deleted"
        except Exception as e:
            results["error"] = str(e)
    return results


# ── Tool: execute_notebook_code ──────────────────────────────────────────────


@mcp.tool()
@NotebookState.state_dependent
async def execute_notebook_code(
    notebook_path: str,
    execution_type: str,
    position_index: int = None,
    package_names: str = None,
) -> Union[dict, str]:
    r"""Execute code in a Jupyter notebook on the user-provided server.

    This consolidates all code execution operations into a single tool following MCP best practices.

    IMPORTANT: Server URL Configuration
    ----------------------------------
    This tool requires that you first call setup_notebook with the correct server URL:

    Required setup:
        setup_notebook(\"my_notebook\", server_url=\"http://localhost:9999\")

    Then you can use this tool:
        execute_notebook_code(\"my_notebook\", \"execute_cell\", position_index=0)

    Without setup_notebook, this will try to connect to http://localhost:8888 by default.

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
        return await _execute_cell_internal(notebook_path, position_index)
    elif execution_type == "install_packages":
        return await _execute_install_packages(notebook_path, package_names)
    else:
        raise ValueError(
            f"Invalid execution_type: {execution_type}. Must be one of: execute_cell, install_packages"
        )


# ── Execute helpers ───────────────────────────────────────────────────────────


async def _execute_cell_internal(notebook_path: str, position_index: int) -> dict:
    """Execute an existing code cell in a Jupyter notebook."""
    if position_index is None:
        raise ValueError("position_index is required for execute_cell operation")

    notebook_path = _ensure_ipynb_extension(notebook_path)
    kernel = await get_kernel(notebook_path)

    async with notebook_client(notebook_path) as notebook:
        result = await notebook.execute_cell(position_index, kernel)

        if "outputs" in result:
            result["outputs"] = filter_image_outputs(result["outputs"])

        return result


async def _execute_install_packages(notebook_path: str, package_names: str) -> str:
    """Install packages using uv pip in the notebook environment."""
    if not package_names:
        raise ValueError("package_names is required for install_packages operation")

    logger.info(f"Installing packages: {package_names}")

    notebook_path = _ensure_ipynb_extension(notebook_path)

    try:
        current_kernel = await get_kernel(notebook_path)
    except McpError:
        raise

    try:
        async with notebook_client(notebook_path) as notebook:
            cell_content = f"!uv pip install {package_names}"
            cell_index = await notebook.add_code_cell(cell_content)
            result = await notebook.execute_cell(cell_index, current_kernel)

            outputs = result.get("outputs", [])
            if len(outputs) > 0:
                outputs = filter_image_outputs(outputs)

            if len(outputs) == 0:
                installation_result = "No output from installation command"
            else:
                installation_result = [extract_output(output) for output in outputs]

            return f"Installation of packages [{package_names}]: {installation_result}"

    except Exception as e:
        logger.error(f"Error installing packages: {e}")
        return f"Error: {str(e)}"


# ── Tool: setup_notebook ─────────────────────────────────────────────────────


@mcp.tool()
@NotebookState.refreshes_state
async def setup_notebook(notebook_path: str, server_url: str = None) -> dict:
    r"""Prepare notebook for use and connect to the kernel on the user-provided server.
    Will create a new empty Jupyter notebook if needed on the server.

    **CALL THIS FIRST** - This tool must be called before using other notebook tools
    to establish the server URL connection. All subsequent notebook operations will
    use the server URL stored by this tool.

    This tool creates an empty notebook. To add content, use the modify_notebook_cells
    tool after creation:

    Example usage:
        # Step 1: REQUIRED - Setup notebook with correct server URL
        setup_notebook("demo", server_url="http://localhost:9999")

        # Step 2: Add cells (these now use the stored server URL automatically)
        modify_notebook_cells("demo", "add_markdown", "# Title\\n\\nDescription")
        modify_notebook_cells("demo", "add_code", "print('Hello World')")

    This tool assumes a Jupyter server is already running and accessible at the specified
    `server_url`. It connects to this existing server to manage the notebook.

    Note that notebook_path must be relative to the Jupyter server root, not an absolute
    filesystem path.

    Args:
        notebook_path: Path to the notebook, relative to the Jupyter server root.
        server_url: Jupyter server URL (HIGHLY RECOMMENDED to specify explicitly).
                    This URL will be stored and used for subsequent interactions with this notebook.
                    If not provided, defaults to http://localhost:8888 which may not be correct for your setup.
                    Common values: http://localhost:8888, http://localhost:9999, etc.

    Returns
    -------
        dict: Information about the notebook and status message.
    """
    notebook_path = _ensure_ipynb_extension(notebook_path)

    if server_url is not None:
        NotebookState.set_server_url(notebook_path, server_url)
    server_url = NotebookState.get_server_url(notebook_path)

    info = await prepare_notebook(notebook_path, server_url, TOKEN)

    if "content" in info and info["content"]:
        if "cells" in info["content"]:
            info["content"]["cells"] = _filter_cell_outputs(info["content"]["cells"])

    await anyio.sleep(0.5)
    await NotebookState.update_hash(notebook_path, server_url, caller="notebook_final")

    return info


# ── Server creation ───────────────────────────────────────────────────────────


def create_server(
    host: str = "127.0.0.1", port: int = 8000, stateless_http: bool = False
) -> FastMCP:
    """Create and configure the FastMCP server instance."""
    global mcp
    if host != "127.0.0.1" or port != 8000 or stateless_http:
        mcp = FastMCP("notebook", host=host, port=port, stateless_http=stateless_http)

        mcp.tool()(query_notebook)
        mcp.tool()(modify_notebook_cells)
        mcp.tool()(execute_notebook_code)
        mcp.tool()(setup_notebook)

    return mcp


if __name__ == "__main__":
    transport = "stdio"
    if len(sys.argv) > 1:
        if sys.argv[1] in ["--http", "-h"]:
            transport = "streamable-http"

    server = create_server()
    logger.info(f"Starting MCP notebook server with {transport} transport")
    server.run(transport=transport)
