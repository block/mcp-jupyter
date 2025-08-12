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

TOKEN = os.getenv("TOKEN", "BLOCK")


def _ensure_ipynb_extension(notebook_path: str) -> str:
    """Ensure the notebook path has the .ipynb extension.

    Args:
        notebook_path: Path to a notebook file

    Returns
    -------
        str: The notebook path with .ipynb extension
    """
    if not notebook_path.endswith(".ipynb"):
        return f"{notebook_path}.ipynb"
    return notebook_path


def extract_output(output: dict) -> str:
    """Extract output from a Jupyter notebook cell.

    Args:
        output: Output dictionary from cell execution

    Returns
    -------
        str: The extracted output text. For different output types:
            - display_data: returns data["text/plain"]
            - execute_result: returns data["text/plain"]
            - stream: returns text
            - error: returns traceback
            - other: returns empty string

    Raises
    ------
        KeyError: If required keys are missing from the output dictionary
    """
    if output["output_type"] == "display_data":
        return output["data"]["text/plain"]
    elif output["output_type"] == "execute_result":
        return output["data"]["text/plain"]
    elif output["output_type"] == "stream":
        return output["text"]
    elif output["output_type"] == "error":
        return output["traceback"]
    else:
        return ""
