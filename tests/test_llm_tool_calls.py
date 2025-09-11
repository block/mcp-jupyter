"""Test that an LLM can generate correct MCP tool calls for notebook operations."""

import pytest

from mcp_jupyter.server import query_notebook

from .llm_providers.config import get_test_providers

LLM_PROVIDERS = get_test_providers()


def get_test_task() -> str:
    return """
1. Check if the Jupyter server is running
2. Create a new notebook called 'math_functions'
3. Add a function that calculates the area of a circle
4. Add another function that calculates the factorial of a number
5. Edit the first cell to add a proper docstring and test the function
"""


@pytest.mark.llm
@pytest.mark.asyncio
@pytest.mark.parametrize("provider", LLM_PROVIDERS, ids=lambda p: p.name)
async def test_llm_generates_correct_tool_calls(llm_jupyter_server, provider):
    """Test that an LLM provider can generate correct MCP tool calls."""
    print(f"\n{'=' * 80}")
    print(f"Testing {provider.name.upper()} provider")
    print(f"{'=' * 80}")

    try:
        task_prompt = get_test_task()

        async for progress_message in provider.send_task(
            prompt=task_prompt, server_url=llm_jupyter_server, verbose=True
        ):
            print(progress_message)

        response = await provider.get_final_response()

        print(f"\n{'=' * 80}")
        print(f"{provider.name.upper()} RESPONSE SUMMARY")
        print(f"{'=' * 80}")
        print(f"Success: {response.success}")
        print(f"Tool calls made: {response.tool_calls_made}")
        print(f"Error: {response.error or 'None'}")
        print(f"Response text length: {len(response.text)} characters")
        if response.metadata:
            print(f"Metadata: {response.metadata}")

        assert response.success, f"{provider.name} should have completed successfully"
        assert response.tool_calls_made > 0, (
            f"{provider.name} should have made tool calls"
        )

        all_cells = query_notebook(
            "math_functions", "view_source", server_url=llm_jupyter_server
        )
        assert len(all_cells) >= 2, f"Expected at least 2 cells, got {len(all_cells)}"

        function_cells = [
            cell
            for cell in all_cells
            if cell.get("cell_type") == "code" and "def " in cell.get("source", "")
        ]
        assert len(function_cells) >= 2, (
            f"Expected at least 2 function definitions, got {len(function_cells)}"
        )

        source_text = " ".join([cell.get("source", "") for cell in all_cells])
        assert "area" in source_text.lower() or "circle" in source_text.lower(), (
            "Expected circle area function"
        )
        assert "factorial" in source_text.lower(), "Expected factorial function"

        executed_cells = [
            cell for cell in all_cells if cell.get("execution_count") is not None
        ]
        assert len(executed_cells) > 0, "Expected at least one cell to be executed"

        first_code_cell = next(
            (cell for cell in all_cells if cell.get("cell_type") == "code"), None
        )
        if first_code_cell:
            source = first_code_cell.get("source", "")
            has_docstring = '"""' in source or "'''" in source or 'r"""' in source
            if has_docstring:
                print("✓ Found docstring in first cell as requested")

        print(f"\n{'=' * 80}")
        print(f"{provider.name.upper()} SUCCESS SUMMARY")
        print(f"{'=' * 80}")
        print(f"✓ Successfully created notebook with {len(all_cells)} cells")
        print(f"✓ Found {len(function_cells)} function definitions")
        print(f"✓ Found {len(executed_cells)} executed cells")
        print(f"✓ {provider.name} successfully generated MCP tool calls!")

    finally:
        await provider.cleanup()
