import asyncio
import logging
import os
from typing import List

import httpx

TOKEN = os.getenv("TOKEN", "BLOCK")

_http_client: httpx.AsyncClient | None = None
_http_client_loop_id: int | None = None


def get_http_client() -> httpx.AsyncClient:
    """Get or create the shared async HTTP client.

    Detects event loop changes (e.g. between test functions) and creates a
    fresh client bound to the current loop when needed.
    """
    global _http_client, _http_client_loop_id
    current_loop_id = None
    try:
        current_loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        pass

    if _http_client is None or (
        current_loop_id is not None and _http_client_loop_id != current_loop_id
    ):
        _http_client = httpx.AsyncClient(timeout=10.0)
        _http_client_loop_id = current_loop_id
    return _http_client


async def close_http_client():
    """Close the shared async HTTP client."""
    global _http_client, _http_client_loop_id
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
        _http_client_loop_id = None


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


def filter_image_outputs(outputs: List[dict]) -> List[dict]:
    """Filter out base64 images and replace with text indicators.

    Args:
        outputs: List of output dictionaries from cell execution

    Returns
    -------
        List[dict]: Filtered outputs with images replaced by text indicators
    """
    filtered_outputs = []

    for output in outputs:
        # Create a copy of the output to avoid modifying the original
        filtered_output = output.copy()

        # Check for image data in display_data or execute_result outputs
        if output.get("output_type") in ["display_data", "execute_result"]:
            data = output.get("data", {})
            if data:
                # Create a copy of data to avoid modifying the original
                filtered_data = data.copy()

                # Check for various image formats and replace with text indicators
                image_types = ["image/png", "image/jpeg", "image/svg+xml", "image/gif"]
                images_found = []

                for img_type in image_types:
                    if img_type in filtered_data:
                        # Remove the base64 image data
                        del filtered_data[img_type]
                        images_found.append(img_type.split("/")[1].upper())

                if images_found:
                    # Add a text indicator for the removed images
                    image_indicator = (
                        f"Image generated ({', '.join(images_found)} format)"
                    )
                    if "text/plain" in filtered_data:
                        # If there's already text/plain content (like "<Figure size...>"),
                        # append the indicator to show image was filtered
                        existing_text = filtered_data["text/plain"]

                        # Handle both string and list formats
                        if isinstance(existing_text, list):
                            existing_text_str = "".join(existing_text)
                        else:
                            existing_text_str = existing_text

                        if "Figure" in existing_text_str or "Axes" in existing_text_str:
                            # Keep the existing figure description and add our indicator
                            if isinstance(existing_text, list):
                                filtered_data["text/plain"] = existing_text + [
                                    f" - {image_indicator}"
                                ]
                            else:
                                filtered_data["text/plain"] = (
                                    existing_text + f" - {image_indicator}"
                                )
                        else:
                            # For other text, append on new line
                            if isinstance(existing_text, list):
                                filtered_data["text/plain"] = existing_text + [
                                    f"\n{image_indicator}"
                                ]
                            else:
                                filtered_data["text/plain"] = (
                                    existing_text + f"\n{image_indicator}"
                                )
                    else:
                        # Create new text/plain output
                        filtered_data["text/plain"] = image_indicator

                filtered_output["data"] = filtered_data

        filtered_outputs.append(filtered_output)

    return filtered_outputs


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
