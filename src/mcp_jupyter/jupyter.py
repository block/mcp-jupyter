import logging
import os
import signal
import subprocess
import time
from typing import Any, Dict, Optional

import requests
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, ErrorData

# Setup logger for the jupyter module
logger = logging.getLogger(__name__)


def check_server_status(server_url: str, token: str) -> bool:
    """Check if a Jupyter server is running at the given URL.

    Args:
        server_url: The server URL to check
        token: Authentication token

    Returns
    -------
        bool: True if server is running, False otherwise
    """
    try:
        response = requests.get(
            f"{server_url}/api/sessions",
            headers={"Authorization": f"token {token}"},
        )
        return response.status_code == 200
    except requests.ConnectionError:
        return False


def list_running_sessions(server_url: str, token: str) -> Dict[str, Any]:
    """List all running notebook sessions.

    Args:
        server_url: The server URL
        token: Authentication token

    Returns
    -------
        Dict[str, Any]: JSON response from server with session information

    Raises
    ------
        RequestException: If unable to connect to server
    """
    response = requests.get(
        f"{server_url}/api/sessions",
        headers={"Authorization": f"token {token}"},
    )
    response.raise_for_status()
    return response.json()
