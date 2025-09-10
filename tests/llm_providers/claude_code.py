"""Claude Code provider for MCP tool call testing."""

from typing import AsyncGenerator

from claude_code_sdk import AssistantMessage, TextBlock, query

from .base import LLMProvider, LLMResponse


class ClaudeCodeProvider(LLMProvider):
    """Provider that uses Claude Code SDK to generate MCP tool calls."""

    def __init__(self):
        self._responses = []
        self._message_count = 0
        self._verbose = False

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "claude-code"

    async def send_task(
        self, prompt: str, server_url: str, verbose: bool = False
    ) -> AsyncGenerator[str, None]:
        """Send task to Claude Code and yield progress messages."""
        self._verbose = verbose
        self._responses = []
        self._message_count = 0

        # Create the full task prompt
        full_prompt = f"""Using the MCP Jupyter server at {server_url}, please:

{prompt}

Make sure to execute the cells so we can see the output."""

        if verbose:
            yield f"Sending query to Claude Code: {full_prompt}"
            yield "=" * 80
            yield "Claude Code is working..."
            yield "=" * 80

        # Send query to Claude Code and process responses
        async for message in query(prompt=full_prompt):
            self._message_count += 1

            # Filter out internal metadata messages
            message_type = type(message).__name__
            if message_type == "ResultMessage":
                continue

            if verbose:
                yield f"\n--- Message {self._message_count} ---"
                yield f"Message type: {message_type}"

            if isinstance(message, AssistantMessage):
                for i, block in enumerate(message.content):
                    if verbose:
                        yield f"Block {i+1} type: {type(block).__name__}"

                    if isinstance(block, TextBlock):
                        self._responses.append(block.text)
                        if verbose:
                            yield f"Claude: {block.text}"
                    else:
                        if verbose:
                            yield f"Other content: {block}"
            else:
                if verbose:
                    # Only show meaningful system messages, not all internal ones
                    if message_type not in ["SystemMessage"]:
                        yield f"Other message: {message}"

        if verbose:
            yield "=" * 80
            yield f"Claude Code finished. Total messages: {self._message_count}"
            yield "=" * 80

    async def get_final_response(self) -> LLMResponse:
        """Get the final response from Claude Code."""
        success = len(self._responses) > 0
        full_text = "\n".join(self._responses)

        return LLMResponse(
            text=full_text,
            tool_calls_made=self._message_count,
            success=success,
            error=None if success else "No responses received from Claude Code",
            metadata={
                "provider": "claude-code",
                "message_count": self._message_count,
                "response_count": len(self._responses),
            },
        )

    async def cleanup(self):
        """Clean up Claude Code provider resources."""
        self._responses = []
        self._message_count = 0
