"""Async REST-based notebook client for Jupyter.

Uses httpx for async HTTP and caches notebook content in memory
to avoid redundant fetches. Mutations update the cache and save
back to the server.
"""

import functools
import json
import logging
from typing import Any, Dict, List, Optional

import anyio

from .utils import get_http_client

logger = logging.getLogger(__name__)


class NotebookClient:
    """Async REST-based Jupyter notebook client.

    Content is cached after connect(). Read-only access (cells, _doc, __getitem__)
    uses the cache synchronously. Mutations (add/edit/delete/execute) are async
    and update both server and cache.
    """

    def __init__(
        self, server_url: str, notebook_path: str, token: Optional[str] = None
    ):
        self._server_url = server_url.rstrip("/")
        self._notebook_path = notebook_path
        self._token = token
        self._cached_content: Optional[Dict[str, Any]] = None

    @property
    def connected(self) -> bool:
        """Check if client has cached content (connected)."""
        return self._cached_content is not None

    @property
    def cells(self) -> List[Dict[str, Any]]:
        """Get all cells from cache."""
        if self._cached_content is None:
            return []
        return self._cached_content.get("cells", [])

    @property
    def _doc(self):
        """Compatibility property for code that accesses notebook._doc.ycells."""

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

    def _make_auth_headers(self) -> Dict[str, str]:
        """Create authorization headers."""
        headers = {}
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        return headers

    async def _refresh_content(self):
        """Fetch notebook content from server into cache."""
        client = get_http_client()
        response = await client.get(
            f"{self._server_url}/api/contents/{self._notebook_path}",
            headers=self._make_auth_headers(),
        )
        if response.status_code == 404:
            await self._create_empty_notebook()
            return await self._refresh_content()
        response.raise_for_status()
        self._cached_content = response.json().get("content", {})

    async def connect(self) -> None:
        """Connect to server and pre-fetch notebook content."""
        client = get_http_client()
        response = await client.get(
            f"{self._server_url}/api/contents",
            headers=self._make_auth_headers(),
        )
        response.raise_for_status()
        await self._refresh_content()
        logger.info(f"Connected to Jupyter server at {self._server_url}")

    async def disconnect(self) -> None:
        """Disconnect from server."""
        self._cached_content = None
        logger.info("Disconnected from Jupyter server")

    async def _get_default_kernel_info(self) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Get default kernel specification from server."""
        client = get_http_client()
        response = await client.get(
            f"{self._server_url}/api/kernelspecs",
            headers=self._make_auth_headers(),
        )
        response.raise_for_status()
        data = response.json()

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

        language_info = {"name": spec.get("language", "python")}
        metadata = spec.get("metadata", {})
        if "interpreter" in metadata:
            interpreter = metadata["interpreter"]
            if "version" in interpreter:
                language_info["version"] = interpreter["version"]

        return kernelspec, language_info

    async def _create_empty_notebook(self) -> None:
        """Create an empty notebook on the server."""
        kernelspec, language_info = await self._get_default_kernel_info()

        empty_notebook = {
            "cells": [],
            "metadata": {
                "kernelspec": kernelspec,
                "language_info": language_info,
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }

        client = get_http_client()
        response = await client.put(
            f"{self._server_url}/api/contents/{self._notebook_path}",
            headers=self._make_auth_headers(),
            json={"type": "notebook", "content": empty_notebook},
        )
        response.raise_for_status()
        logger.info(f"Created empty notebook: {self._notebook_path}")

    async def _save_notebook(self, notebook_content: Dict[str, Any]) -> None:
        """Save notebook content to server and update cache."""
        client = get_http_client()
        response = await client.put(
            f"{self._server_url}/api/contents/{self._notebook_path}",
            headers=self._make_auth_headers(),
            json={"type": "notebook", "content": notebook_content},
        )
        response.raise_for_status()
        self._cached_content = notebook_content
        logger.debug("Notebook saved successfully")

    async def add_code_cell(self, content: str) -> int:
        """Add a code cell at the end. Returns position index."""
        if self._cached_content is None:
            await self._refresh_content()

        cell = {
            "cell_type": "code",
            "source": content,
            "metadata": {},
            "outputs": [],
            "execution_count": None,
        }

        self._cached_content["cells"].append(cell)
        await self._save_notebook(self._cached_content)
        return len(self._cached_content["cells"]) - 1

    async def insert_code_cell(self, position: int, content: str) -> None:
        """Insert a code cell at a specific position."""
        if self._cached_content is None:
            await self._refresh_content()

        cell = {
            "cell_type": "code",
            "source": content,
            "metadata": {},
            "outputs": [],
            "execution_count": None,
        }

        max_position = len(self._cached_content["cells"])
        if position > max_position:
            position = max_position

        self._cached_content["cells"].insert(position, cell)
        await self._save_notebook(self._cached_content)

    async def add_markdown_cell(self, content: str) -> int:
        """Add a markdown cell at the end. Returns position index."""
        if self._cached_content is None:
            await self._refresh_content()

        cell = {"cell_type": "markdown", "source": content, "metadata": {}}

        self._cached_content["cells"].append(cell)
        await self._save_notebook(self._cached_content)
        return len(self._cached_content["cells"]) - 1

    async def insert_markdown_cell(self, position: int, content: str) -> None:
        """Insert a markdown cell at a specific position."""
        if self._cached_content is None:
            await self._refresh_content()

        cell = {"cell_type": "markdown", "source": content, "metadata": {}}

        max_position = len(self._cached_content["cells"])
        if position > max_position:
            position = max_position

        self._cached_content["cells"].insert(position, cell)
        await self._save_notebook(self._cached_content)

    async def edit_cell(self, position: int, new_content: str) -> None:
        """Edit the content of a cell at the specified position."""
        if self._cached_content is None:
            await self._refresh_content()

        cells = self._cached_content["cells"]
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")

        cells[position]["source"] = new_content
        await self._save_notebook(self._cached_content)

    async def delete_cell(self, position: int) -> None:
        """Delete a cell at the specified position."""
        if self._cached_content is None:
            await self._refresh_content()

        cells = self._cached_content["cells"]
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")

        cells.pop(position)
        await self._save_notebook(self._cached_content)

    async def execute_cell(self, position: int, kernel_client) -> Dict[str, Any]:
        """Execute a code cell using the provided kernel client.

        kernel_client.execute() is blocking, so it runs in a worker thread.
        """
        if self._cached_content is None:
            await self._refresh_content()

        cells = self._cached_content["cells"]
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")

        cell = cells[position]
        if cell["cell_type"] != "code":
            raise ValueError(f"Cell at position {position} is not a code cell")

        source = cell["source"]
        result = await anyio.to_thread.run_sync(
            functools.partial(kernel_client.execute, source)
        )

        cell["outputs"] = result.get("outputs", [])
        cell["execution_count"] = result.get("execution_count")
        await self._save_notebook(self._cached_content)

        return result

    def get_cell(self, position: int) -> Dict[str, Any]:
        """Get a cell by position (sync, from cache)."""
        cells = self.cells
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")
        return cells[position]

    async def set_cell(self, position: int, cell_data: Dict[str, Any]) -> None:
        """Set cell content at position (async, saves to server)."""
        if self._cached_content is None:
            await self._refresh_content()

        cells = self._cached_content["cells"]
        if position >= len(cells):
            raise IndexError(f"Cell index {position} out of range")

        cells[position] = cell_data
        await self._save_notebook(self._cached_content)

    def refresh(self) -> None:
        """No-op for backward compatibility. Use _refresh_content() for async refresh."""
        pass

    def __getitem__(self, position: int) -> Dict[str, Any]:
        """Get a cell by position using bracket notation (sync, from cache)."""
        return self.get_cell(position)

    async def __aenter__(self):
        """Async context manager support."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager support."""
        await self.disconnect()
        return False
