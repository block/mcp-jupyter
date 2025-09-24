"""Simple REST-based notebook client for Jupyter.

This module provides a clean, reliable interface to Jupyter notebooks using
only REST API calls. It avoids the complexity of RTC/WebSocket connections
while still benefiting from server-side collaborative features.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

# Setup logger
logger = logging.getLogger(__name__)


class NotebookClient:
    """Simple REST-based Jupyter notebook client.

    This client uses only REST API calls to interact with Jupyter notebooks,
    avoiding the complexity and reliability issues of WebSocket/RTC connections.
    The server-side RTC infrastructure still provides collaboration benefits
    for other clients.  It maintains the same interface as the
    jupyter_nbmodel_client.NbModelClient RTC client.
    """

    def __init__(
        self, server_url: str, notebook_path: str, token: Optional[str] = None
    ):
        """Initialize the notebook client.

        Args:
            server_url: Base Jupyter server URL (e.g., http://localhost:8888)
            notebook_path: Path to notebook relative to server root
            token: Authentication token for the server
        """
        self._server_url = server_url.rstrip("/")
        self._notebook_path = notebook_path
        self._token = token
        self._connected = False
        self._notebook_content: Optional[Dict[str, Any]] = None

    @property
    def connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    @property
    def cells(self) -> List[Dict[str, Any]]:
        """Get all cells as a list of dictionaries."""
        if not self._notebook_content:
            return []
        return self._notebook_content.get("cells", [])

    @property
    def _doc(self):
        """Compatibility property to access cells like the old RTC client.

        This provides compatibility with code that accesses notebook._doc.ycells.to_py().
        """

        class CellsWrapper:
            def __init__(self, cells):
                self._cells = cells

            def to_py(self):
                return self._cells

            def __iter__(self):
                return iter(self._cells)

            def __len__(self):
                return len(self._cells)

            def __getitem__(self, index):
                return self._cells[index]

        class DocWrapper:
            def __init__(self, cells):
                self.ycells = CellsWrapper(cells)

        return DocWrapper(self.cells)

    def _make_request_headers(self) -> Dict[str, str]:
        """Create headers for REST requests."""
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        return headers

    def _get_default_kernel_info(self) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Get default kernel specification from the Jupyter server.

        Returns
        -------
            tuple: (kernelspec, language_info) dictionaries

        Raises
        ------
            requests.RequestException: If unable to get kernel specs from server
        """
        # Get available kernel specs
        response = requests.get(
            f"{self._server_url}/api/kernelspecs",
            headers=self._make_request_headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        # Get default kernel name (usually 'python3' or similar)
        default_kernel_name = data.get("default", "python3")
        kernelspecs = data.get("kernelspecs", {})

        if default_kernel_name not in kernelspecs:
            raise RuntimeError(
                f"Default kernel '{default_kernel_name}' not found in available kernelspecs"
            )

        spec = kernelspecs[default_kernel_name]["spec"]
        kernelspec = {
            "display_name": spec.get("display_name", "Python 3"),
            "language": spec.get("language", "python"),
            "name": default_kernel_name,
        }

        # Extract language info
        language_info = {
            "name": spec.get("language", "python"),
        }

        # Add version if available in metadata
        metadata = spec.get("metadata", {})
        if "interpreter" in metadata:
            interpreter = metadata["interpreter"]
            if "version" in interpreter:
                language_info["version"] = interpreter["version"]

        return kernelspec, language_info

    def connect(self) -> None:
        """Connect to the Jupyter server and load notebook content."""
        try:
            # Test server connection
            response = requests.get(
                f"{self._server_url}/api/contents",
                headers=self._make_request_headers(),
                timeout=10,
            )
            response.raise_for_status()

            # Load notebook content
            self._load_notebook_content()
            self._connected = True
            logger.info(f"✅ Connected to Jupyter server at {self._server_url}")

        except Exception as e:
            logger.error(f"❌ Failed to connect to Jupyter server: {e}")
            raise

    def disconnect(self) -> None:
        """Disconnect from the server."""
        self._connected = False
        self._notebook_content = None
        logger.info("Disconnected from Jupyter server")

    def _load_notebook_content(self) -> None:
        """Load notebook content from the server."""
        try:
            response = requests.get(
                f"{self._server_url}/api/contents/{self._notebook_path}",
                headers=self._make_request_headers(),
                timeout=10,
            )

            if response.status_code == 404:
                # Notebook doesn't exist, create empty one
                self._create_empty_notebook()
            else:
                response.raise_for_status()
                data = response.json()
                self._notebook_content = data.get("content", {})
                logger.debug(f"Loaded notebook with {len(self.cells)} cells")

        except Exception as e:
            logger.error(f"Failed to load notebook content: {e}")
            raise

    def _create_empty_notebook(self) -> None:
        """Create an empty notebook on the server."""
        # Get default kernel spec from Jupyter server
        kernelspec, language_info = self._get_default_kernel_info()

        empty_notebook = {
            "cells": [],
            "metadata": {
                "kernelspec": kernelspec,
                "language_info": language_info,
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }

        notebook_data = {"type": "notebook", "content": empty_notebook}

        response = requests.put(
            f"{self._server_url}/api/contents/{self._notebook_path}",
            headers=self._make_request_headers(),
            data=json.dumps(notebook_data),
            timeout=10,
        )
        response.raise_for_status()

        self._notebook_content = empty_notebook
        logger.info(f"Created empty notebook: {self._notebook_path}")

    def _save_notebook(self) -> None:
        """Save current notebook content to the server."""
        if not self._notebook_content:
            return

        notebook_data = {"type": "notebook", "content": self._notebook_content}

        response = requests.put(
            f"{self._server_url}/api/contents/{self._notebook_path}",
            headers=self._make_request_headers(),
            data=json.dumps(notebook_data),
            timeout=10,
        )
        response.raise_for_status()
        logger.debug("Notebook saved successfully")

    def add_code_cell(self, content: str) -> int:
        """Add a code cell at the end of the notebook.

        Args:
            content: Source code for the cell

        Returns
        -------
            Position index where the cell was inserted
        """
        if not self._notebook_content:
            raise RuntimeError("Not connected to notebook")

        cell = {
            "cell_type": "code",
            "source": content,
            "metadata": {},
            "outputs": [],
            "execution_count": None,
        }

        self._notebook_content["cells"].append(cell)
        self._save_notebook()
        return len(self._notebook_content["cells"]) - 1

    def insert_code_cell(self, position: int, content: str) -> None:
        """Insert a code cell at a specific position.

        Args:
            position: Position to insert at (0-indexed)
            content: Source code for the cell
        """
        if not self._notebook_content:
            raise RuntimeError("Not connected to notebook")

        cell = {
            "cell_type": "code",
            "source": content,
            "metadata": {},
            "outputs": [],
            "execution_count": None,
        }

        # Ensure position is within bounds
        max_position = len(self._notebook_content["cells"])
        if position > max_position:
            position = max_position

        self._notebook_content["cells"].insert(position, cell)
        self._save_notebook()

    def add_markdown_cell(self, content: str) -> int:
        """Add a markdown cell at the end of the notebook.

        Args:
            content: Markdown content for the cell

        Returns
        -------
            Position index where the cell was inserted
        """
        if not self._notebook_content:
            raise RuntimeError("Not connected to notebook")

        cell = {"cell_type": "markdown", "source": content, "metadata": {}}

        self._notebook_content["cells"].append(cell)
        self._save_notebook()
        return len(self._notebook_content["cells"]) - 1

    def insert_markdown_cell(self, position: int, content: str) -> None:
        """Insert a markdown cell at a specific position.

        Args:
            position: Position to insert at (0-indexed)
            content: Markdown content for the cell
        """
        if not self._notebook_content:
            raise RuntimeError("Not connected to notebook")

        cell = {"cell_type": "markdown", "source": content, "metadata": {}}

        # Ensure position is within bounds
        max_position = len(self._notebook_content["cells"])
        if position > max_position:
            position = max_position

        self._notebook_content["cells"].insert(position, cell)
        self._save_notebook()

    def edit_cell(self, position: int, new_content: str) -> None:
        """Edit the content of a cell at the specified position.

        Args:
            position: Position of the cell to edit (0-indexed)
            new_content: New content for the cell
        """
        if not self._notebook_content:
            raise RuntimeError("Not connected to notebook")

        cells = self._notebook_content["cells"]
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")

        cells[position]["source"] = new_content
        self._save_notebook()

    def delete_cell(self, position: int) -> None:
        """Delete a cell at the specified position.

        Args:
            position: Position of the cell to delete (0-indexed)
        """
        if not self._notebook_content:
            raise RuntimeError("Not connected to notebook")

        cells = self._notebook_content["cells"]
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")

        cells.pop(position)
        self._save_notebook()

    def execute_cell(self, position: int, kernel_client) -> Dict[str, Any]:
        """Execute a code cell using the provided kernel client.

        Args:
            position: Position of the cell to execute (0-indexed)
            kernel_client: The kernel client to use for execution

        Returns
        -------
            Execution results containing outputs and execution count
        """
        if not self._notebook_content:
            raise RuntimeError("Not connected to notebook")

        cells = self._notebook_content["cells"]
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")

        cell = cells[position]
        if cell["cell_type"] != "code":
            raise ValueError(f"Cell at position {position} is not a code cell")

        # Execute using the existing kernel client
        result = kernel_client.execute(cell["source"])

        # Update cell with results
        cell["outputs"] = result.get("outputs", [])
        cell["execution_count"] = result.get("execution_count")
        self._save_notebook()

        return result

    def get_cell(self, position: int) -> Dict[str, Any]:
        """Get a cell by position.

        Args:
            position: Position of the cell (0-indexed)

        Returns
        -------
            Cell data as dictionary
        """
        if not self._notebook_content:
            raise RuntimeError("Not connected to notebook")

        cells = self._notebook_content["cells"]
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")

        return cells[position]

    def refresh(self) -> None:
        """Refresh notebook content from server to detect external changes."""
        if self._connected:
            self._load_notebook_content()

    def __getitem__(self, position: int) -> Dict[str, Any]:
        """Get a cell by position using bracket notation.

        Args:
            position: Position of the cell (0-indexed)

        Returns
        -------
            Cell data as dictionary
        """
        return self.get_cell(position)

    def __setitem__(self, position: int, cell_data: Dict[str, Any]) -> None:
        """Set cell content using bracket notation.

        Args:
            position: Position of the cell (0-indexed)
            cell_data: New cell data dictionary
        """
        if not self._notebook_content:
            raise RuntimeError("Not connected to notebook")

        cells = self._notebook_content["cells"]
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")

        # Update the cell in place
        cells[position] = cell_data
        self._save_notebook()
