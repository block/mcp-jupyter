"""Tests for filtering functions that remove verbose output data."""

import pytest

from mcp_jupyter.server import _filter_cell_outputs
from mcp_jupyter.utils import filter_image_outputs


class TestFilterImageOutputs:
    """Test filter_image_outputs function from utils.py."""

    def test_filter_png_image(self):
        """Test filtering of PNG image data."""
        outputs = [
            {
                "output_type": "display_data",
                "data": {
                    "text/plain": ["<Figure size 640x480 with 1 Axes>"],
                    "image/png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==",
                },
            }
        ]

        filtered = filter_image_outputs(outputs)

        assert len(filtered) == 1
        assert "image/png" not in filtered[0]["data"]
        assert "text/plain" in filtered[0]["data"]
        text_plain = filtered[0]["data"]["text/plain"]
        assert isinstance(text_plain, list)
        assert "Image generated (PNG format)" in "".join(text_plain)

    def test_filter_multiple_image_formats(self):
        """Test filtering of multiple image formats."""
        outputs = [
            {
                "output_type": "execute_result",
                "data": {
                    "text/plain": ["<matplotlib.figure.Figure>"],
                    "image/png": "base64_png_data_here",
                    "image/jpeg": "base64_jpeg_data_here",
                    "image/svg+xml": "<svg>...</svg>",
                },
            }
        ]

        filtered = filter_image_outputs(outputs)

        assert len(filtered) == 1
        data = filtered[0]["data"]
        assert "image/png" not in data
        assert "image/jpeg" not in data
        assert "image/svg+xml" not in data
        assert "text/plain" in data
        text_plain = data["text/plain"]
        assert isinstance(text_plain, list)
        assert "Image generated (PNG, JPEG, SVG+XML format)" in "".join(text_plain)

    def test_preserve_non_image_data(self):
        """Test that non-image data is preserved."""
        outputs = [
            {"output_type": "stream", "name": "stdout", "text": ["Hello World\n"]},
            {
                "output_type": "execute_result",
                "data": {"text/plain": ["42"], "text/html": ["<b>42</b>"]},
            },
        ]

        filtered = filter_image_outputs(outputs)

        assert len(filtered) == 2
        # Stream output should be unchanged
        assert filtered[0] == outputs[0]
        # Execute result without images should be unchanged
        assert filtered[1] == outputs[1]

    def test_no_data_field(self):
        """Test outputs without data field."""
        outputs = [
            {
                "output_type": "display_data"
                # No data field
            }
        ]

        filtered = filter_image_outputs(outputs)

        assert len(filtered) == 1
        assert filtered[0] == outputs[0]

    def test_create_text_plain_when_missing(self):
        """Test creating text/plain field when it doesn't exist."""
        outputs = [
            {"output_type": "display_data", "data": {"image/png": "base64_data_here"}}
        ]

        filtered = filter_image_outputs(outputs)

        assert len(filtered) == 1
        assert "image/png" not in filtered[0]["data"]
        assert filtered[0]["data"]["text/plain"] == "Image generated (PNG format)"


class TestFilterCellOutputs:
    """Test _filter_cell_outputs function from server.py."""

    def test_filter_single_cell_with_image(self):
        """Test filtering a single code cell with image output."""
        cell = {
            "cell_type": "code",
            "source": [
                "import matplotlib.pyplot as plt\n",
                "plt.plot([1,2,3])\n",
                "plt.show()",
            ],
            "execution_count": 1,
            "outputs": [
                {
                    "output_type": "display_data",
                    "data": {
                        "text/plain": ["<Figure size 640x480 with 1 Axes>"],
                        "image/png": "very_long_base64_string_here...",
                    },
                }
            ],
            "metadata": {},
        }

        filtered = _filter_cell_outputs(cell)

        assert filtered["cell_type"] == "code"
        assert filtered["source"] == cell["source"]
        assert filtered["execution_count"] == 1
        assert len(filtered["outputs"]) == 1

        output = filtered["outputs"][0]
        assert output["output_type"] == "display_data"
        assert "[filtered]" in output["data"]
        assert "Image data present" in output["data"]["[filtered]"]

    def test_filter_single_cell_with_html(self):
        """Test filtering a single code cell with HTML output."""
        cell = {
            "cell_type": "code",
            "source": [
                "import pandas as pd\n",
                "df = pd.DataFrame({'A': [1,2,3]})\n",
                "df",
            ],
            "execution_count": 2,
            "outputs": [
                {
                    "output_type": "execute_result",
                    "data": {
                        "text/html": [
                            "<div><table><tr><td>A</td></tr><tr><td>1</td></tr></table></div>"
                        ],
                        "text/plain": ["   A\n0  1\n1  2\n2  3"],
                    },
                }
            ],
        }

        filtered = _filter_cell_outputs(cell)

        assert filtered["cell_type"] == "code"
        assert len(filtered["outputs"]) == 1

        output = filtered["outputs"][0]
        assert "[filtered]" in output["data"]
        assert "HTML data present" in output["data"]["[filtered]"]

    def test_preserve_text_outputs(self):
        """Test that text-only outputs are preserved."""
        cell = {
            "cell_type": "code",
            "source": ["print('Hello World')"],
            "execution_count": 3,
            "outputs": [
                {"output_type": "stream", "name": "stdout", "text": ["Hello World\n"]}
            ],
        }

        filtered = _filter_cell_outputs(cell)

        assert len(filtered["outputs"]) == 1
        output = filtered["outputs"][0]
        assert output["text"] == ["Hello World\n"]
        assert output["name"] == "stdout"

    def test_filter_markdown_cell(self):
        """Test filtering a markdown cell (should preserve all content)."""
        cell = {
            "cell_type": "markdown",
            "source": ["# Title\n", "\n", "Some markdown content."],
            "metadata": {},
        }

        filtered = _filter_cell_outputs(cell)

        assert filtered["cell_type"] == "markdown"
        assert filtered["source"] == cell["source"]
        assert (
            "execution_count" not in filtered
        )  # Markdown cells don't have execution_count

    def test_filter_list_of_cells(self):
        """Test filtering a list of cells."""
        cells = [
            {"cell_type": "markdown", "source": ["# Introduction"], "metadata": {}},
            {
                "cell_type": "code",
                "source": ["print('test')"],
                "execution_count": 1,
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": ["test\n"]}
                ],
            },
        ]

        filtered = _filter_cell_outputs(cells)

        assert len(filtered) == 2
        assert filtered[0]["cell_type"] == "markdown"
        assert filtered[1]["cell_type"] == "code"
        assert filtered[1]["outputs"][0]["text"] == ["test\n"]

    def test_keep_small_text_data(self):
        """Test that small text data is preserved."""
        cell = {
            "cell_type": "code",
            "source": ["x = 42\n", "x"],
            "execution_count": 1,
            "outputs": [
                {"output_type": "execute_result", "data": {"text/plain": ["42"]}}
            ],
        }

        filtered = _filter_cell_outputs(cell)

        output = filtered["outputs"][0]
        assert output["data"] == {"text/plain": ["42"]}  # Should be preserved as-is

    def test_handle_non_dict_cell(self):
        """Test handling of non-dict input."""
        non_dict = "not a dictionary"

        filtered = _filter_cell_outputs(non_dict)

        assert filtered == non_dict  # Should return unchanged
