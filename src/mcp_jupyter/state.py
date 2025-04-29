import hashlib
import json
import logging
import time
from functools import wraps
from typing import Optional

import requests
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from .utils import TOKEN, _ensure_ipynb_extension

# Setup logger
logger = logging.getLogger(__name__)


class NotebookState:
    """Tracks the state of the notebook (or more precisely, Goose's knowledge of the
    notebook state).

    This class provides class methods for:
    - Tracking notebook content hash based on a user-provided Jupyter server.
    - Checking for notebook changes against the user-provided server.
    - Decorators for state-dependent and state-refreshing operations.
    - Managing server URLs associated with notebook paths (relative to the server root).

    Notebook paths are assumed to be relative to the root directory of the
    user-provided Jupyter server.

    Raises
    ------
        McpError: When state-dependent operations are attempted with outdated state
    """

    contents_hash: str = ""
    # Add a dictionary to store server URLs for each notebook path
    notebook_server_urls: dict = {}

    @classmethod
    def get_server_url(cls, notebook_path: str) -> str:
        """Get the server URL associated with a notebook path (relative to server root).

        Args:
            notebook_path: Path to the notebook file, relative to the Jupyter server root.

        Returns
        -------
            str: The server URL associated with this notebook, or the default URL
        """
        notebook_path = _ensure_ipynb_extension(notebook_path)
        return cls.notebook_server_urls.get(notebook_path, "http://localhost:8888")

    @classmethod
    def set_server_url(cls, notebook_path: str, server_url: str):
        """Associate a server URL with a notebook path (relative to server root).

        Args:
            notebook_path: Path to the notebook file, relative to the Jupyter server root.
            server_url: Server URL to associate with this notebook
        """
        notebook_path = _ensure_ipynb_extension(notebook_path)
        cls.notebook_server_urls[notebook_path] = server_url
        logger.info(f"Associated notebook {notebook_path} with server URL {server_url}")

    @classmethod
    def _get_new_hash(cls, notebook_path: str, server_url: str = None) -> str:
        """Hash the notebook contents from the user-provided Jupyter server.

        Args:
            notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                           relative to the Jupyter server root.
            server_url: The server URL to use. Defaults to None.

        Returns
        -------
            str: SHA-256 hash of the notebook contents

        Raises
        ------
            RequestException: If unable to fetch notebook contents
            IOError: If unable to read notebook file
        """
        # Ensure the notebook path has the .ipynb extension
        notebook_path = _ensure_ipynb_extension(notebook_path)

        # Use the stored server_url if none is provided
        if server_url is None:
            server_url = cls.get_server_url(notebook_path)

        # Empirically this seems to be long enough that autosaving kicks in after a change.
        # Also tried fetching source in other ways and triggering saves to avoid sleeping, but
        # haven't found a good way to get this working reliably.
        time.sleep(1.5)

        response = requests.get(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {TOKEN}"},
        )

        response.raise_for_status()
        notebook_content = response.json()["content"]

        return hashlib.sha256(json.dumps(notebook_content).encode()).hexdigest()

    @classmethod
    def update_hash(
        cls, notebook_path: str, server_url: str = None, caller: Optional[str] = None
    ):
        """Update the stored hash of notebook contents from the user-provided server.

        Args:
            notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                           relative to the Jupyter server root.
            server_url: The server URL to use. Defaults to None.
            caller: Optional name of calling function for logging

        Returns
        -------
            None

        Raises
        ------
            RequestException: If unable to fetch notebook contents
            IOError: If unable to read notebook file
        """
        # Ensure the notebook path has the .ipynb extension
        notebook_path = _ensure_ipynb_extension(notebook_path)

        old_hash = cls.contents_hash
        cls.contents_hash = cls._get_new_hash(notebook_path, server_url)
        prefix = f"[{caller}] " if caller else ""
        if old_hash != cls.contents_hash:
            logger.info(
                f"{prefix}Updated notebook hash from {old_hash!r} to "
                f"{cls.contents_hash!r}."
            )
        else:
            logger.info(
                f"{prefix}No change in notebook hash (still {cls.contents_hash!r})."
            )

    @classmethod
    def check_for_changes(cls, notebook_path: str, server_url: str = None) -> dict:
        """Check if the notebook has changed on the user-provided server.

        Args:
            notebook_path: Path to the notebook file (.ipynb extension will be added if missing),
                           relative to the Jupyter server root.
            server_url: The server URL to use. Defaults to None.

        Returns
        -------
            dict: Contains:
                - has_changed: bool indicating if notebook changed
                - new_hash: str new content hash
                - old_hash: str previous content hash

        Raises
        ------
            RequestException: If unable to fetch notebook contents
            IOError: If unable to read notebook file
        """
        # Ensure the notebook path has the .ipynb extension
        notebook_path = _ensure_ipynb_extension(notebook_path)

        hashed = cls._get_new_hash(notebook_path, server_url)
        has_changed = cls.contents_hash and hashed != cls.contents_hash
        return {
            "has_changed": has_changed,
            "new_hash": hashed,
            "old_hash": cls.contents_hash,
        }

    @classmethod
    def state_dependent(cls, func):
        """Decorate functions that goose should only use if it knows the current
        state of the notebook.
        State_dependent functions will raise an error if the notebook has changed since the last
        the contents_hash attribute was updated in order to encourage goose to view the notebook
        source. After the wrapped function executes, the contents_hash will be updated to
        reflect the new state.

        Args:
            func: The function to decorate.

        Returns
        -------
            The decorated function.

        Raises
        ------
            OutdatedStateError: If the notebook has changed since the last time the contents_hash
                attribute was updated.
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract notebook_path from args/kwargs
            if args and len(args) > 0:
                notebook_path = args[0]
            elif "notebook_path" in kwargs:
                notebook_path = kwargs["notebook_path"]
            else:
                raise ValueError(
                    "notebook_path (relative to server root) must be provided as first argument or keyword argument"
                )

            # Get server_url from kwargs or use default
            server_url = kwargs.get("server_url", None)

            # Ensure the notebook path has the .ipynb extension and update the args/kwargs
            notebook_path = _ensure_ipynb_extension(notebook_path)
            if args and len(args) > 0:
                args = list(args)
                args[0] = notebook_path
                args = tuple(args)
            else:
                kwargs["notebook_path"] = notebook_path

            changes = cls.check_for_changes(notebook_path, server_url)
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

            result = func(*args, **kwargs)
            cls.update_hash(notebook_path, server_url, caller=func.__name__)
            return result

        return wrapper

    @classmethod
    def refreshes_state(cls, func):
        """Decorate functions that update goose's knowledge of the notebook but
        do not require checking state before execution. I.e. use `state_dependent` for functions
        that goose should not execute unless it knows the notebook state; use `refreshes_state` if
        you merely want execution of the function to refresh goose's knowledge of current state.

        Args:
            func: The function to decorate.

        Returns
        -------
            The decorated function.
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract notebook_path from args/kwargs
            if args and len(args) > 0:
                notebook_path = args[0]
            elif "notebook_path" in kwargs:
                notebook_path = kwargs["notebook_path"]
            else:
                raise ValueError(
                    "notebook_path (relative to server root) must be provided as first argument or keyword argument"
                )

            # Get server_url from kwargs or use default
            server_url = kwargs.get("server_url", None)

            # Ensure the notebook path has the .ipynb extension and update the args/kwargs
            notebook_path = _ensure_ipynb_extension(notebook_path)
            if args and len(args) > 0:
                args = list(args)
                args[0] = notebook_path
                args = tuple(args)
            else:
                kwargs["notebook_path"] = notebook_path

            result = func(*args, **kwargs)
            cls.update_hash(notebook_path, server_url, caller=func.__name__)
            return result

        return wrapper
