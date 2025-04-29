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


def _extract_execution_count(execution_count: Union[str, int, float]) -> int:
    """Extract the int version of the execution count from a string. We make the user provide this
    as a parenthesized string to avoid confusion with the positional index that NBModelClient
    uses under the hood (and not square brackets because this causes all kinds of problems with
    pydantic, I think goose auto converts square brackets either to a list or to a string with
    quotes included).

    Args:
        execution_count: the index (execution_count) that is visible to the user in the notebook UI.
            Formatted like "(19)", a string starting and ending with parentheses, not including
            quotes.

    Returns
    -------
        int: the int execution count without the parentheses
    """
    if isinstance(execution_count, int):
        return execution_count

    if isinstance(execution_count, float):
        return int(execution_count)

    # Try parentheses format first
    if execution_count.startswith("(") and execution_count.endswith(")"):
        try:
            return int(float(execution_count.strip("()")))
        except ValueError:
            pass

    # Try plain string format
    try:
        # First try as integer
        return int(execution_count)
    except ValueError:
        # Then try as float (in case execution_count is something like "1.0")
        try:
            return int(float(execution_count))
        except ValueError:
            raise ValueError(
                f"Invalid execution_count: {execution_count!r}. "
                "Should be an integer, a string like '19', or a string like '(19)'."
            )


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
