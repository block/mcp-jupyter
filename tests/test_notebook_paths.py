"""Tests for Jupyter notebook path handling, especially with remote Jupyter servers."""

import os
import unittest
from unittest.mock import MagicMock, call, patch

import requests
from mcp.shared.exceptions import McpError

from mcp_jupyter.notebook import (
    check_notebook_exists,
    create_new_notebook,
    get_notebook_info,
    prepare_notebook,
    start_notebook_kernel,
)
from mcp_jupyter.utils import _ensure_ipynb_extension

# Mock responses
mock_success_response = MagicMock()
mock_success_response.status_code = 200
mock_success_response.json.return_value = {"name": "test.ipynb", "path": "test.ipynb"}

mock_404_response = MagicMock()
mock_404_response.status_code = 404

mock_create_response = MagicMock()
mock_create_response.status_code = 201  # Typically 201 for created


@patch("requests.put", return_value=mock_create_response)
@patch("requests.get", return_value=mock_success_response)
class TestNotebookPaths(unittest.TestCase):
    """Test notebook path handling functionality."""

    def setUp(self):
        """Set up test fixtures, if any."""
        # Access mocks via self if needed, but they are reset automatically
        # by the decorator context usually. Explicit reset for clarity.
        # We access them via the arguments injected into the test methods.
        pass  # No assignments needed here, mocks are handled per test method

    def test_check_notebook_exists_correct_path(self, mock_get, mock_put):
        """Test that check_notebook_exists uses the relative path."""
        # Setup specific mock behavior for this test
        mock_get.return_value = mock_success_response
        mock_get.reset_mock()  # Reset before use in test
        mock_put.reset_mock()

        # Test
        notebook_path = "subfolder/my_notebook.ipynb"
        server_url = "http://remote.server:8888"
        token = "test-token"
        result = check_notebook_exists(notebook_path, server_url, token)

        # Assert
        mock_get.assert_called_once_with(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {token}"},
        )
        self.assertTrue(result)

    def test_create_notebook_correct_path(self, mock_get, mock_put):
        """Test that create_new_notebook uses the relative path."""
        # Setup
        # Simulate directory already exists for this test case
        mock_get.return_value = mock_success_response
        mock_put.return_value = mock_create_response
        mock_get.reset_mock()
        mock_put.reset_mock()

        # Test with a path that includes subdirectories
        notebook_path = "subfolder/my_notebook"  # Function adds .ipynb
        expected_notebook_path_ext = "subfolder/my_notebook.ipynb"
        directory_path = "subfolder"
        cells = ["print('Hello')"]
        server_url = "http://remote.server:8888"
        token = "test-token"

        # Execute
        create_new_notebook(notebook_path, cells, server_url, token)

        # Assert
        # Check that GET was called to check the directory
        mock_get.assert_called_once_with(
            f"{server_url}/api/contents/{directory_path}",
            headers={"Authorization": f"token {token}"},
        )
        # Check PUT was called once (only for the notebook file)
        mock_put.assert_called_once()
        put_call_args = mock_put.call_args
        self.assertEqual(
            put_call_args[0][0],
            f"{server_url}/api/contents/{expected_notebook_path_ext}",
        )
        self.assertEqual(put_call_args[1]["headers"]["Authorization"], f"token {token}")

    def test_create_notebook_creates_directory(self, mock_get, mock_put):
        """Test that create_new_notebook creates the directory if it doesn't exist."""
        # Setup
        notebook_path = "new_folder/my_test_notebook"  # Function adds .ipynb
        expected_notebook_path_ext = "new_folder/my_test_notebook.ipynb"
        directory_path = "new_folder"
        server_url = "http://remote.server:8888"
        token = "test-token"
        cells = ["print('hello dir')"]

        # Configure mocks for this test:
        mock_get.return_value = mock_404_response
        mock_put.return_value = mock_create_response
        # Ensure raise_for_status on the PUT response mock doesn't raise
        mock_put.return_value.raise_for_status = MagicMock()
        mock_get.reset_mock()
        mock_put.reset_mock()

        # Execute
        create_new_notebook(notebook_path, cells, server_url, token)

        # Assert
        # Check that GET was called to check the directory
        mock_get.assert_called_once_with(
            f"{server_url}/api/contents/{directory_path}",
            headers={"Authorization": f"token {token}"},
        )

        # Check that PUT was called twice
        self.assertEqual(mock_put.call_count, 2)

        # Get the actual calls made to the mock
        put_calls = mock_put.call_args_list

        # Assert the directory creation call details
        dir_call_expected = call(
            f"{server_url}/api/contents/{directory_path}",
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
            },
            json={"type": "directory"},
        )
        self.assertEqual(put_calls[0], dir_call_expected)

        # Assert the notebook creation call details (check URL, token, type)
        notebook_call_actual = put_calls[1]
        self.assertEqual(
            notebook_call_actual[0][0],
            f"{server_url}/api/contents/{expected_notebook_path_ext}",
        )  # Check URL arg
        self.assertEqual(
            notebook_call_actual[1]["headers"]["Authorization"], f"token {token}"
        )  # Check token in kwargs['headers']
        self.assertEqual(
            notebook_call_actual[1]["json"]["type"], "notebook"
        )  # Check type in kwargs['json']

        # Ensure raise_for_status was called on the mock responses
        self.assertEqual(mock_create_response.raise_for_status.call_count, 2)

    def test_get_notebook_info_correct_path(self, mock_get, mock_put):
        """Test that get_notebook_info uses the relative path."""
        # Setup specific mock behavior
        mock_get.return_value = mock_success_response
        mock_get.reset_mock()
        mock_put.reset_mock()

        # Test
        notebook_path = "another/folder/info_test.ipynb"
        server_url = "http://host.com:9999"
        token = "info-token"
        get_notebook_info(notebook_path, server_url, token)

        # Assert
        mock_get.assert_called_once_with(
            f"{server_url}/api/contents/{notebook_path}",
            headers={"Authorization": f"token {token}"},
        )

    def test_prepare_notebook_end_to_end(self, mock_get, mock_put):
        """Test the prepare_notebook function creates and starts kernel."""
        # Setup Mocks for prepare_notebook sequence:
        # 1. check_notebook_exists (GET /api/contents/...) -> 404
        # 2. create_new_notebook -> directory check (GET /api/contents/...) -> 404
        # 3. create_new_notebook -> directory create (PUT /api/contents/...) -> 201
        # 4. create_new_notebook -> notebook create (PUT /api/contents/...) -> 201
        # 5. list_notebook_sessions (GET /api/sessions) -> [] (no existing session)
        # 6. start_notebook_kernel -> session create (POST /api/sessions) -> 200 (or 201)
        # 7. get_notebook_info (GET /api/contents/...) -> 200

        mock_post_response = MagicMock()  # For POST /api/sessions
        mock_post_response.status_code = 201
        mock_post_response.json.return_value = {
            "id": "kernel-123",
            "path": "prep/end_to_end.ipynb",
            "kernel": {"id": "k1"},
        }
        mock_post_response.raise_for_status = MagicMock()

        # Use side_effect for multiple calls with different responses
        mock_get.side_effect = [
            mock_404_response,  # 1. check_notebook_exists
            mock_404_response,  # 2. create_new_notebook (dir check)
            MagicMock(status_code=200, json=lambda: []),  # 5. list_notebook_sessions
            mock_success_response,  # 7. get_notebook_info
        ]
        # PUT is called twice (dir, then notebook)
        mock_put.return_value = mock_create_response
        mock_put.return_value.raise_for_status = MagicMock()

        mock_get.reset_mock()
        mock_put.reset_mock()

        # Patch requests.post specifically for this test
        with patch("requests.post", return_value=mock_post_response) as mock_post:
            # Test
            notebook_path = "prep/end_to_end"
            expected_notebook_path_ext = "prep/end_to_end.ipynb"
            server_url = "http://prepare.it:8888"
            token = "prep-token"
            cells = ["import os"]
            result = prepare_notebook(notebook_path, cells, server_url, token)

        # Assertions
        # Check GET calls
        get_calls = mock_get.call_args_list
        self.assertEqual(len(get_calls), 4)
        self.assertEqual(
            get_calls[0],
            call(
                f"{server_url}/api/contents/{expected_notebook_path_ext}",
                headers={"Authorization": f"token {token}"},
            ),
        )  # Check exists
        self.assertEqual(
            get_calls[1],
            call(
                f"{server_url}/api/contents/prep",
                headers={"Authorization": f"token {token}"},
            ),
        )  # Create dir check
        self.assertEqual(
            get_calls[2],
            call(
                f"{server_url}/api/sessions",
                headers={"Authorization": f"token {token}"},
            ),
        )  # List sessions
        self.assertEqual(
            get_calls[3],
            call(
                f"{server_url}/api/contents/{expected_notebook_path_ext}",
                headers={"Authorization": f"token {token}"},
            ),
        )  # Get info

        # Check PUT calls (dir + notebook)
        self.assertEqual(mock_put.call_count, 2)
        put_calls = mock_put.call_args_list
        self.assertEqual(
            put_calls[0],
            call(
                f"{server_url}/api/contents/prep",
                headers={
                    "Authorization": f"token {token}",
                    "Content-Type": "application/json",
                },
                json={"type": "directory"},
            ),
        )
        self.assertEqual(
            put_calls[1][0][0],
            f"{server_url}/api/contents/{expected_notebook_path_ext}",
        )  # Check URL of notebook PUT
        self.assertEqual(put_calls[1][1]["headers"]["Authorization"], f"token {token}")

        # Check POST call (start kernel)
        mock_post.assert_called_once()
        post_call_args = mock_post.call_args
        self.assertEqual(post_call_args[0][0], f"{server_url}/api/sessions")
        self.assertEqual(post_call_args[1]["json"]["path"], expected_notebook_path_ext)
        self.assertEqual(
            post_call_args[1]["headers"]["Authorization"], f"token {token}"
        )

        # Check result content
        self.assertIn("message", result)
        self.assertTrue(result["message"].endswith("created"))
        self.assertEqual(
            result["path"], "test.ipynb"
        )  # From mock_success_response json

    def test_start_kernel_correct_path(self, mock_get, mock_put):
        """Test that start_notebook_kernel uses the relative path and checks sessions."""
        # Setup Mocks
        # 1. list_notebook_sessions (GET /api/sessions) -> [] (no existing session)
        # 2. start_notebook_kernel -> session create (POST /api/sessions) -> 200 (or 201)

        mock_post_response = MagicMock()
        mock_post_response.status_code = 201
        mock_post_response.json.return_value = {
            "id": "kernel-xyz",
            "path": "start/me/up.ipynb",
            "kernel": {"id": "k2"},
        }
        mock_post_response.raise_for_status = MagicMock()

        # Mock GET for list_notebook_sessions to return empty list
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_get.return_value.raise_for_status = MagicMock()  # Mock raise_for_status

        mock_get.reset_mock()
        mock_put.reset_mock()

        # Patch requests.post specifically for this test
        with patch("requests.post", return_value=mock_post_response) as mock_post:
            # Test
            notebook_path = "start/me/up"
            expected_notebook_path_ext = "start/me/up.ipynb"
            server_url = "http://start.it:8888"
            token = "start-token"
            start_notebook_kernel(notebook_path, server_url, token)

        # Assertions
        # Check GET call (list sessions)
        mock_get.assert_called_once_with(
            f"{server_url}/api/sessions", headers={"Authorization": f"token {token}"}
        )

        # Check POST call (create session)
        mock_post.assert_called_once()
        post_call_args = mock_post.call_args
        self.assertEqual(post_call_args[0][0], f"{server_url}/api/sessions")  # URL
        self.assertEqual(
            post_call_args[1]["headers"]["Authorization"], f"token {token}"
        )  # Header
        self.assertEqual(
            post_call_args[1]["json"]["path"], expected_notebook_path_ext
        )  # Body path
        self.assertEqual(post_call_args[1]["json"]["type"], "notebook")  # Body type


if __name__ == "__main__":
    unittest.main()
