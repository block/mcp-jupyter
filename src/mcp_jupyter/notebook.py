"""Async Jupyter notebook management module for MCP.

All notebook_path parameters are relative to the Jupyter server root directory.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from .utils import _ensure_ipynb_extension, get_http_client

logger = logging.getLogger(__name__)


async def check_notebook_exists(notebook_path: str, server_url: str, token: str) -> bool:
    """Check if a notebook exists at the given path."""
    notebook_path = _ensure_ipynb_extension(notebook_path)
    try:
        client = get_http_client()
        response = await client.get(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {token}"},
        )
        return response.status_code == 200
    except Exception:
        return False


async def create_new_notebook(notebook_path: str, server_url: str, token: str) -> None:
    """Create a new empty Jupyter notebook."""
    notebook_path = _ensure_ipynb_extension(notebook_path)
    directory_path = os.path.dirname(notebook_path)

    client = get_http_client()
    auth_headers = {"Authorization": f"token {token}"}

    if directory_path:
        try:
            dir_check = await client.get(
                f"{server_url}/api/contents/{directory_path}",
                headers=auth_headers,
            )
            if dir_check.status_code == 404:
                logger.info(f"Directory {directory_path} not found, creating it.")
                dir_create = await client.put(
                    f"{server_url}/api/contents/{directory_path}",
                    headers=auth_headers,
                    json={"type": "directory"},
                )
                dir_create.raise_for_status()
                logger.info(f"Successfully created directory {directory_path}")
            elif dir_check.status_code >= 400:
                dir_check.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"Error checking or creating directory {directory_path}: {e}")
            raise McpError(
                ErrorData(
                    code=INTERNAL_ERROR,
                    message=f"Could not ensure directory exists: {e}",
                )
            )

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

    try:
        create_response = await client.put(
            f"{server_url}/api/contents/{notebook_path}",
            headers=auth_headers,
            json=notebook_content,
        )
        create_response.raise_for_status()
        logger.info(f"Created new notebook at {notebook_path}")
    except httpx.RequestError as e:
        logger.error(f"Error creating notebook: {e}")
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"Could not create notebook: {e}",
            )
        )


async def list_notebook_sessions(server_url: str, token: str) -> List[Dict[str, Any]]:
    """List all notebook sessions."""
    try:
        client = get_http_client()
        response = await client.get(
            f"{server_url}/api/sessions",
            headers={"Authorization": f"token {token}"},
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error listing notebook sessions: {e}")
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"Could not list notebook sessions: {str(e)}",
            )
        )


async def start_notebook_kernel(
    notebook_path: str, server_url: str, token: str
) -> Dict[str, Any]:
    """Start a kernel for a notebook."""
    notebook_path = _ensure_ipynb_extension(notebook_path)

    sessions = await list_notebook_sessions(server_url, token)
    session_exists = any(session["path"] == notebook_path for session in sessions)

    if session_exists:
        logger.info(f"Kernel already running for notebook {notebook_path}")
        return next(session for session in sessions if session["path"] == notebook_path)

    session_data = {
        "kernel": {"name": "python3"},
        "name": os.path.basename(notebook_path),
        "path": notebook_path,
        "type": "notebook",
    }

    try:
        client = get_http_client()
        kernel_response = await client.post(
            f"{server_url}/api/sessions",
            headers={"Authorization": f"token {token}"},
            json=session_data,
        )
        kernel_response.raise_for_status()
        logger.info(f"Started kernel for notebook {notebook_path}")
        return kernel_response.json()
    except Exception as e:
        logger.error(f"Error starting kernel: {e}")
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"Could not start kernel for notebook: {str(e)}",
            )
        )


async def get_notebook_info(
    notebook_path: str, server_url: str, token: str
) -> Dict[str, Any]:
    """Get information about a notebook."""
    notebook_path = _ensure_ipynb_extension(notebook_path)

    try:
        client = get_http_client()
        response = await client.get(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {token}"},
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error getting notebook info: {e}")
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"Could not get notebook info: {str(e)}",
            )
        )


async def prepare_notebook(
    notebook_path: str,
    server_url: str = "http://localhost:8888",
    token: str = None,
) -> Dict[str, Any]:
    """Prepare notebook for use and start kernel."""
    if token is None:
        token = os.getenv("TOKEN", "BLOCK")

    notebook_path = _ensure_ipynb_extension(notebook_path)

    try:
        notebook_exists = await check_notebook_exists(notebook_path, server_url, token)

        if not notebook_exists:
            await create_new_notebook(notebook_path, server_url, token)
        else:
            logger.info(f"Notebook {notebook_path} already exists")

        await start_notebook_kernel(notebook_path, server_url, token)
        info = await get_notebook_info(notebook_path, server_url, token)

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
