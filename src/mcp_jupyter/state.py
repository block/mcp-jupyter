import hashlib
import json
import logging
from functools import wraps
from typing import Optional

import anyio
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from .utils import TOKEN, _ensure_ipynb_extension, get_http_client

logger = logging.getLogger(__name__)


class NotebookState:
    """Tracks the state of notebooks with per-notebook content hashes.

    All methods that perform HTTP are async. The decorators state_dependent
    and refreshes_state produce async wrappers.
    """

    _contents_hashes: dict[str, str] = {}
    notebook_server_urls: dict = {}

    @classmethod
    def get_server_url(cls, notebook_path: str) -> str:
        """Get the server URL associated with a notebook path."""
        notebook_path = _ensure_ipynb_extension(notebook_path)
        return cls.notebook_server_urls.get(notebook_path, "http://localhost:8888")

    @classmethod
    def set_server_url(cls, notebook_path: str, server_url: str):
        """Associate a server URL with a notebook path."""
        notebook_path = _ensure_ipynb_extension(notebook_path)
        cls.notebook_server_urls[notebook_path] = server_url
        logger.info(f"Associated notebook {notebook_path} with server URL {server_url}")

    @classmethod
    async def _get_new_hash(
        cls,
        notebook_path: str,
        server_url: str = None,
        known_content: str = None,
    ) -> str:
        """Hash notebook contents. If known_content is provided, skip the HTTP fetch."""
        notebook_path = _ensure_ipynb_extension(notebook_path)

        if known_content is not None:
            return hashlib.sha256(known_content.encode()).hexdigest()

        if server_url is None:
            server_url = cls.get_server_url(notebook_path)

        # Reduced from 1.5s — brief pause for autosave
        await anyio.sleep(0.3)

        client = get_http_client()
        response = await client.get(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {TOKEN}"},
        )
        response.raise_for_status()
        notebook_content = response.json()["content"]
        return hashlib.sha256(json.dumps(notebook_content).encode()).hexdigest()

    @classmethod
    async def update_hash(
        cls,
        notebook_path: str,
        server_url: str = None,
        caller: Optional[str] = None,
        known_content: str = None,
    ):
        """Update the stored hash of notebook contents."""
        notebook_path = _ensure_ipynb_extension(notebook_path)
        old_hash = cls._contents_hashes.get(notebook_path, "")
        new_hash = await cls._get_new_hash(notebook_path, server_url, known_content)
        cls._contents_hashes[notebook_path] = new_hash
        prefix = f"[{caller}] " if caller else ""
        if old_hash != new_hash:
            logger.info(
                f"{prefix}Updated notebook hash for {notebook_path} "
                f"from {old_hash!r} to {new_hash!r}."
            )
        else:
            logger.info(
                f"{prefix}No change in notebook hash for {notebook_path} "
                f"(still {new_hash!r})."
            )

    @classmethod
    async def check_for_changes(cls, notebook_path: str, server_url: str = None) -> dict:
        """Check if the notebook has changed since last seen."""
        notebook_path = _ensure_ipynb_extension(notebook_path)
        hashed = await cls._get_new_hash(notebook_path, server_url)
        old_hash = cls._contents_hashes.get(notebook_path, "")
        has_changed = bool(old_hash) and hashed != old_hash
        return {
            "has_changed": has_changed,
            "new_hash": hashed,
            "old_hash": old_hash,
        }

    @classmethod
    def state_dependent(cls, func):
        """Decorator: raise error if notebook changed since last seen, then update hash."""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            if args and len(args) > 0:
                notebook_path = args[0]
            elif "notebook_path" in kwargs:
                notebook_path = kwargs["notebook_path"]
            else:
                raise ValueError(
                    "notebook_path must be provided as first argument or keyword argument"
                )

            server_url = kwargs.get("server_url", None)
            notebook_path = _ensure_ipynb_extension(notebook_path)
            if args and len(args) > 0:
                args = list(args)
                args[0] = notebook_path
                args = tuple(args)
            else:
                kwargs["notebook_path"] = notebook_path

            changes = await cls.check_for_changes(notebook_path, server_url)
            if changes["has_changed"]:
                raise McpError(
                    ErrorData(
                        code=INTERNAL_ERROR,
                        message=f"Notebook has changed since you last saw it ({changes['old_hash']}"
                        f" --> {changes['new_hash']}). Use your view_source tool to "
                        "update your knowledge of the notebook contents. If you are trying to "
                        "edit/delete a specific cell, you can likely start by viewing just that "
                        "cell rather than the whole notebook.",
                    )
                )

            result = await func(*args, **kwargs)
            await cls.update_hash(notebook_path, server_url, caller=func.__name__)
            return result

        return wrapper

    @classmethod
    def refreshes_state(cls, func):
        """Decorator: update hash after function executes (no pre-check)."""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            if args and len(args) > 0:
                notebook_path = args[0]
            elif "notebook_path" in kwargs:
                notebook_path = kwargs["notebook_path"]
            else:
                raise ValueError(
                    "notebook_path must be provided as first argument or keyword argument"
                )

            server_url = kwargs.get("server_url", None)
            notebook_path = _ensure_ipynb_extension(notebook_path)
            if args and len(args) > 0:
                args = list(args)
                args[0] = notebook_path
                args = tuple(args)
            else:
                kwargs["notebook_path"] = notebook_path

            result = await func(*args, **kwargs)
            await cls.update_hash(notebook_path, server_url, caller=func.__name__)
            return result

        return wrapper
