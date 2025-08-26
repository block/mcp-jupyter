"""Tests for filtering functions that remove verbose output data."""

import pytest

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
