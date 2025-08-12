"""
Jupyter notebook management module for MCP.

This module provides functions to create, open, and interact with Jupyter notebooks.

Important note about paths:
---------------------------
All notebook_path parameters throughout this module are assumed to be relative to the
Jupyter server root directory, not absolute paths on the local filesystem.

For example, if your Jupyter server is running with root directory at '/home/user/jupyter',
and you want to access a notebook at '/home/user/jupyter/examples/demo.ipynb', you would
use notebook_path='examples/demo.ipynb'.

This is particularly important when using port forwarding to access a Jupyter server running
on a different machine. The paths are always evaluated relative to the server's root, not
the client's filesystem.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from .utils import _ensure_ipynb_extension

# Setup notebook logger
logger = logging.getLogger(__name__)


def check_notebook_exists(notebook_path: str, server_url: str, token: str) -> bool:
    """Check if a notebook exists at the given path.

    Args:
        notebook_path: Path to the notebook, relative to Jupyter server root
        server_url: Jupyter server URL
        token: Authentication token

    Returns
    -------
        bool: True if notebook exists, False otherwise
    """
    notebook_path = _ensure_ipynb_extension(notebook_path)

    try:
        response = requests.get(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {token}"},
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def create_new_notebook(
    notebook_path: str, cells: List[str], server_url: str, token: str
) -> None:
    """Create a new Jupyter notebook.

    Args:
        notebook_path: Path where to create the notebook, relative to Jupyter server root.
                       Intermediate directories will be created if they don't exist.
        cells: List of cell contents to add
        server_url: Jupyter server URL
        token: Authentication token

    Raises
    ------
        McpError: If notebook creation fails
    """
    notebook_path = _ensure_ipynb_extension(notebook_path)
    directory_path = os.path.dirname(notebook_path)

    # 1. Ensure the target directory exists on the server
    if directory_path:  # Only proceed if there's a directory component
        try:
            # Check if directory exists
            dir_check_response = requests.get(
                f"{server_url}/api/contents/{directory_path}",
                headers={"Authorization": f"token {token}"},
            )
            # If directory doesn't exist (404), create it
            if dir_check_response.status_code == 404:
                logger.info(f"Directory {directory_path} not found, creating it.")
                dir_create_response = requests.put(
                    f"{server_url}/api/contents/{directory_path}",
                    headers={
                        "Authorization": f"token {token}",
                        "Content-Type": "application/json",
                    },
                    json={"type": "directory"},
                )
                dir_create_response.raise_for_status()  # Raise exception if directory creation fails
                logger.info(f"Successfully created directory {directory_path}")
            # Raise exception for other non-successful status codes
            elif dir_check_response.status_code >= 400:
                dir_check_response.raise_for_status()

        except requests.RequestException as e:
            logger.error(f"Error checking or creating directory {directory_path}: {e}")
            if hasattr(e, "response") and e.response is not None:
                error_message = (
                    f"Server error: {e.response.status_code} - {e.response.text}"
                )
            else:
                error_message = str(e)
            raise McpError(
                ErrorData(
                    code=INTERNAL_ERROR,
                    message=f"Could not ensure directory exists: {error_message}",
                )
            )

    # 2. Create the notebook file
    # Create a new notebook with default empty structure
    notebook_content = {
        "type": "notebook",
        "content": {
            "metadata": {
                "kernelspec": {
                    "name": "python3",
                    "display_name": "Python 3",
                    "language": "python",
                },
                "language_info": {"name": "python", "version": "3.8"},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": [],
        },
    }

    # Add any specified cells
    if cells:
        for cell_content in cells:
            notebook_content["content"]["cells"].append(
                {
                    "cell_type": "code",
                    "metadata": {},
                    "source": cell_content,
                    "execution_count": None,
                    "outputs": [],
                }
            )

    # Make the API request to create the notebook
    try:
        create_response = requests.put(
            f"{server_url}/api/contents/{notebook_path}",
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
            },
            json=notebook_content,
        )

        create_response.raise_for_status()
        logger.info(f"Created new notebook at {notebook_path}")
    except requests.RequestException as e:
        logger.error(f"Error creating notebook: {e}")
        if hasattr(e, "response") and e.response is not None:
            error_message = (
                f"Server error: {e.response.status_code} - {e.response.text}"
            )
        else:
            error_message = str(e)

        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"Could not create notebook: {error_message}",
            )
        )


def list_notebook_sessions(server_url: str, token: str) -> List[Dict[str, Any]]:
    """List all notebook sessions.

    Args:
        server_url: Jupyter server URL
        token: Authentication token

    Returns
    -------
        List[Dict[str, Any]]: List of session data

    Raises
    ------
        McpError: If unable to list sessions
    """
    try:
        response = requests.get(
            f"{server_url}/api/sessions", headers={"Authorization": f"token {token}"}
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error listing notebook sessions: {e}")
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"Could not list notebook sessions: {str(e)}",
            )
        )


def start_notebook_kernel(
    notebook_path: str, server_url: str, token: str
) -> Dict[str, Any]:
    """Start a kernel for a notebook.

    Args:
        notebook_path: Path to the notebook, relative to Jupyter server root
        server_url: Jupyter server URL
        token: Authentication token

    Returns
    -------
        Dict[str, Any]: Kernel session information

    Raises
    ------
        McpError: If kernel creation fails
    """
    notebook_path = _ensure_ipynb_extension(notebook_path)

    # Check if a kernel is already running for this notebook
    sessions = list_notebook_sessions(server_url, token)
    session_exists = any(session["path"] == notebook_path for session in sessions)

    if session_exists:
        logger.info(f"Kernel already running for notebook {notebook_path}")
        return next(session for session in sessions if session["path"] == notebook_path)

    # Start a new kernel session for this notebook
    session_data = {
        "kernel": {"name": "python3"},
        "name": os.path.basename(notebook_path),
        "path": notebook_path,
        "type": "notebook",
    }

    try:
        kernel_response = requests.post(
            f"{server_url}/api/sessions",
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
            },
            json=session_data,
        )

        kernel_response.raise_for_status()
        logger.info(f"Started kernel for notebook {notebook_path}")
        return kernel_response.json()
    except requests.RequestException as e:
        logger.error(f"Error starting kernel: {e}")
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"Could not start kernel for notebook: {str(e)}",
            )
        )


def get_notebook_info(
    notebook_path: str, server_url: str, token: str
) -> Dict[str, Any]:
    """Get information about a notebook.

    Args:
        notebook_path: Path to the notebook, relative to Jupyter server root
        server_url: Jupyter server URL
        token: Authentication token

    Returns
    -------
        Dict[str, Any]: Notebook information

    Raises
    ------
        McpError: If unable to get notebook info
    """
    notebook_path = _ensure_ipynb_extension(notebook_path)

    try:
        response = requests.get(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {token}"},
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error getting notebook info: {e}")
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"Could not get notebook info: {str(e)}",
            )
        )


def prepare_notebook(
    notebook_path: str,
    cells: Optional[List[str]] = None,
    server_url: str = "http://localhost:8888",
    token: str = None,
) -> Dict[str, Any]:
    """Prepare notebook for use and start kernel.

    Args:
        notebook_path: Path to the notebook, relative to Jupyter server root
        cells: List of cell contents (optional)
        server_url: Jupyter server URL
        token: Authentication token (defaults to env var)

    Returns
    -------
        Dict[str, Any]: Notebook information with status message

    Raises
    ------
        McpError: If notebook preparation fails
    """
    if token is None:
        token = os.getenv("TOKEN", "BLOCK")

    notebook_path = _ensure_ipynb_extension(notebook_path)

    try:
        # Check if notebook exists
        notebook_exists = check_notebook_exists(notebook_path, server_url, token)

        # Create notebook if it doesn't exist
        if not notebook_exists:
            create_new_notebook(notebook_path, cells or [], server_url, token)
            notebook_created = True
        else:
            notebook_created = False
            logger.info(f"Notebook {notebook_path} already exists")

        # Start kernel
        start_notebook_kernel(notebook_path, server_url, token)

        # Get notebook info
        info = get_notebook_info(notebook_path, server_url, token)

        # Add message about notebook creation status
        if notebook_exists:
            info["message"] = f"Notebook {notebook_path} already exists"
        else:
            info["message"] = f"Notebook {notebook_path} created"

        return info

    except Exception as e:
        if not isinstance(e, McpError):
            logger.error(f"Error preparing notebook: {e}")
            raise McpError(
                ErrorData(
                    code=INTERNAL_ERROR, message=f"Could not prepare notebook: {e}"
                )
            )
        raise e
