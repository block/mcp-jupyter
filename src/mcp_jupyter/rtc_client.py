"""RTC Client for direct JupyterLab Real-Time Collaboration integration.

This module provides a replacement for jupyter-nbmodel-client using the
JupyterLab RTC architecture with pycrdt and jupyter-ydoc.

For now, this is a compatibility shim that provides the same interface
but falls back to REST API calls while we develop the full RTC integration.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import requests
from jupyter_ydoc import YNotebook
from pycrdt import Doc

logger = logging.getLogger(__name__)


class CRDTCellsWrapper:
    """Wrapper to provide compatibility with jupyter-nbmodel-client ycells API."""

    def __init__(self, notebook: YNotebook):
        self.notebook = notebook

    def to_py(self) -> List[Dict[str, Any]]:
        """Convert cells to Python dictionary format."""
        return self.notebook.ycells.to_py()

    def pop(self, index: int) -> Dict[str, Any]:
        """Remove and return cell at index."""
        if index >= len(self.notebook.ycells):
            raise IndexError(f"Cell index {index} out of range")

        cell = self.notebook.ycells.to_py()[index]
        self.notebook.ycells.pop(index)
        return cell

    def __iter__(self):
        """Iterate over cells."""
        return iter(self.notebook.ycells.to_py())

    def __len__(self):
        """Get number of cells."""
        return len(self.notebook.ycells)

    def __getitem__(self, index: int):
        """Get cell by index."""
        return self.notebook.ycells.to_py()[index]


class CRDTDocumentWrapper:
    """Wrapper to provide compatibility with jupyter-nbmodel-client _doc API."""

    def __init__(self, notebook: YNotebook):
        self.notebook = notebook
        self.ycells = CRDTCellsWrapper(notebook)


class RTCClient:
    """Real-Time Collaboration client for Jupyter notebooks.

    This class provides a jupyter-nbmodel-client compatible interface
    using the JupyterLab RTC architecture directly.
    """

    def __init__(self, websocket_url: str):
        """Initialize the RTC client.

        Args:
            websocket_url: WebSocket URL to Jupyter server for RTC
        """
        self.websocket_url = websocket_url
        self._crdt_doc = Doc()
        self._notebook = YNotebook(ydoc=self._crdt_doc)
        self._connected = False

        # Extract server info from WebSocket URL for REST API fallback
        parsed = urlparse(websocket_url)
        self._server_url = (
            f"{'https' if parsed.scheme == 'wss' else 'http'}://{parsed.netloc}"
        )
        self._notebook_path = self._extract_notebook_path(websocket_url)
        self._token = self._extract_token(websocket_url)

        # Load initial notebook content
        self._notebook_data = None

    def start(self) -> None:
        """Start the connection to Jupyter server."""
        try:
            self._load_notebook_content()
            self._connected = True
            logger.info("Successfully connected to Jupyter")
        except Exception as e:
            logger.error(f"Failed to start client: {e}")
            raise

    def stop(self) -> None:
        """Stop the connection."""
        self._connected = False
        logger.info("Disconnected from Jupyter")

    def _save_notebook(self) -> None:
        """Save the current notebook content back to the Jupyter server."""
        if not self._connected:
            return

        try:
            headers = {"Content-Type": "application/json"}
            if self._token:
                headers["Authorization"] = f"token {self._token}"

            # Convert YNotebook cells to Jupyter notebook format
            cells = self._notebook.ycells.to_py()

            notebook_content = {
                "cells": cells,
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 4,
            }

            # Save via REST API
            response = requests.put(
                f"{self._server_url}/api/contents/{self._notebook_path}",
                headers=headers,
                json={
                    "type": "notebook",
                    "format": "json",
                    "content": notebook_content,
                },
            )
            response.raise_for_status()
            logger.debug(f"Saved notebook {self._notebook_path} to server")

        except Exception as e:
            logger.warning(f"Failed to save notebook: {e}")

    def _extract_notebook_path(self, websocket_url: str) -> str:
        """Extract notebook path from WebSocket URL."""
        # URL format: ws://localhost:8888/api/collaboration/room/{notebook-path}
        parts = websocket_url.split("/")
        if "room" in parts:
            room_idx = parts.index("room")
            if room_idx + 1 < len(parts):
                return parts[room_idx + 1].split("?")[0]  # Remove query params
        return "unknown.ipynb"

    def _extract_token(self, websocket_url: str) -> Optional[str]:
        """Extract token from WebSocket URL."""
        if "?token=" in websocket_url:
            return websocket_url.split("?token=")[1].split("&")[0]
        return None

    def _load_notebook_content(self) -> None:
        """Load notebook content from Jupyter server using REST API."""
        headers = {}
        if self._token:
            headers["Authorization"] = f"token {self._token}"

        try:
            # Get notebook content
            response = requests.get(
                f"{self._server_url}/api/contents/{self._notebook_path}",
                headers=headers,
            )
            response.raise_for_status()

            self._notebook_data = response.json()

            # Load cells into YNotebook
            if (
                "content" in self._notebook_data
                and "cells" in self._notebook_data["content"]
            ):
                cells = self._notebook_data["content"]["cells"]
                # Clear existing cells and load new ones
                while len(self._notebook.ycells) > 0:
                    self._notebook.ycells.pop(0)

                for cell in cells:
                    self._notebook.append_cell(cell)

        except Exception as e:
            logger.error(f"Failed to load notebook content: {e}")
            # Initialize with empty notebook if loading fails
            self._notebook_data = {
                "content": {
                    "cells": [],
                    "metadata": {},
                    "nbformat": 4,
                    "nbformat_minor": 4,
                }
            }

    @property
    def cells(self) -> List[Dict[str, Any]]:
        """Get all cells as a list of dictionaries."""
        return self._notebook.ycells.to_py()

    @property
    def _doc(self):
        """Compatibility property to access the underlying CRDT document.

        This provides compatibility with the original jupyter-nbmodel-client API
        where code accesses notebook._doc.ycells.to_py() and iterates over cells.
        """
        return CRDTDocumentWrapper(self._notebook)

    @property
    def _lock(self):
        """Compatibility property for locking operations.

        Returns a context manager that can be used with 'with notebook._lock:' syntax.
        In the RTC model, locking is handled by CRDT transactions.
        """
        return self._crdt_doc.transaction()

    def add_code_cell(self, content: str) -> int:
        """Add a code cell at the end of the notebook.

        Args:
            content: Source code for the cell

        Returns
        -------
            Position index where the cell was inserted
        """
        cell = {
            "cell_type": "code",
            "source": content,
            "metadata": {},
            "outputs": [],
            "execution_count": None,
        }

        self._notebook.append_cell(cell)
        self._save_notebook()
        return len(self._notebook.ycells) - 1

    def insert_code_cell(self, position: int, content: str) -> None:
        """Insert a code cell at a specific position.

        Args:
            position: Position to insert at (0-indexed)
            content: Source code for the cell
        """
        cell = {
            "cell_type": "code",
            "source": content,
            "metadata": {},
            "outputs": [],
            "execution_count": None,
        }

        # Use the CRDT array insert method directly
        # Ensure position is within bounds - can insert at end but not beyond
        max_position = len(self._notebook.ycells)
        if position > max_position:
            position = max_position
        self._notebook.ycells.insert(position, cell)
        self._save_notebook()

    def add_markdown_cell(self, content: str) -> int:
        """Add a markdown cell at the end of the notebook.

        Args:
            content: Markdown content for the cell

        Returns
        -------
            Position index where the cell was inserted
        """
        cell = {"cell_type": "markdown", "source": content, "metadata": {}}

        self._notebook.append_cell(cell)
        self._save_notebook()
        return len(self._notebook.ycells) - 1

    def insert_markdown_cell(self, position: int, content: str) -> None:
        """Insert a markdown cell at a specific position.

        Args:
            position: Position to insert at (0-indexed)
            content: Markdown content for the cell
        """
        cell = {"cell_type": "markdown", "source": content, "metadata": {}}

        # Use the CRDT array insert method directly
        self._notebook.ycells.insert(position, cell)
        self._save_notebook()

    def execute_cell(self, position_index: int, kernel) -> Dict[str, Any]:
        """Execute a code cell using the provided kernel.

        Args:
            position_index: Index of the cell to execute
            kernel: Jupyter kernel client for execution

        Returns
        -------
            Dictionary with execution results
        """
        if position_index >= len(self._notebook.ycells):
            raise IndexError(f"Cell index {position_index} out of range")

        cell = self._notebook.ycells.to_py()[position_index]
        if cell.get("cell_type") != "code":
            raise ValueError(f"Cell at index {position_index} is not a code cell")

        source = cell.get("source", "")
        if not source.strip():
            return {"outputs": [], "execution_count": None}

        # Execute the cell using the kernel
        logger.debug(f"Executing code: {source}")
        result = kernel.execute(source)
        logger.debug(f"Execution result: {result}")

        # The kernel.execute() returns the complete result synchronously
        outputs = result.get("outputs", [])
        execution_count = result.get("execution_count")
        status = result.get("status", "ok")

        # Update the cell with execution results
        # Get the current cell data and update it with execution results
        current_cell = self._notebook.ycells.to_py()[position_index]
        updated_cell = current_cell.copy()
        updated_cell["outputs"] = outputs
        updated_cell["execution_count"] = execution_count

        # Replace the cell in the CRDT structure
        self._notebook.ycells.pop(position_index)
        self._notebook.ycells.insert(position_index, updated_cell)
        self._save_notebook()

        return {
            "outputs": outputs,
            "execution_count": execution_count,
            "status": status,
        }

    def delete_cell(self, position_index: int) -> None:
        """Delete a cell at the specified position.

        Args:
            position_index: Index of the cell to delete
        """
        if position_index >= len(self._notebook.ycells):
            raise IndexError(f"Cell index {position_index} out of range")

        self._notebook.ycells.pop(position_index)
        self._save_notebook()

    def __getitem__(self, index: int) -> Dict[str, Any]:
        """Get a cell by index."""
        if index >= len(self._notebook.ycells):
            raise IndexError(f"Cell index {index} out of range")
        return self._notebook.ycells.to_py()[index]

    def __setitem__(self, index: int, cell_data: Dict[str, Any]) -> None:
        """Set a cell's content by index."""
        if index >= len(self._notebook.ycells):
            raise IndexError(f"Cell index {index} out of range")

        # Remove the existing cell and insert the new one
        # This ensures proper CRDT synchronization
        self._notebook.ycells.pop(index)
        self._notebook.ycells.insert(index, cell_data)

        # Trigger notebook save
        self._save_notebook()


def get_jupyter_notebook_websocket_url(
    server_url: str, token: str, path: str, room_id: Optional[str] = None
) -> str:
    """Generate WebSocket URL for Jupyter RTC connection.

    Args:
        server_url: Base Jupyter server URL (http://...)
        token: Jupyter authentication token
        path: Notebook path
        room_id: Optional room ID (defaults to notebook path)

    Returns
    -------
        WebSocket URL for RTC connection
    """
    # Convert HTTP URL to WebSocket URL
    parsed = urlparse(server_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"

    if room_id is None:
        # Use notebook path as room ID, but clean it up for WebSocket use
        room_id = path.replace("/", "_").replace("\\", "_")

    # Build WebSocket URL for RTC
    # The format should be: ws://host/api/collaboration/room/{room_id}
    ws_url = f"{ws_scheme}://{parsed.netloc}/api/collaboration/room/{room_id}"

    # Add token as query parameter if provided
    if token:
        ws_url += f"?token={token}"

    return ws_url
