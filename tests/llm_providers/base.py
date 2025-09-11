"""Base interface for LLM providers in MCP tool call tests."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, Optional


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    text: str
    """The text response from the LLM."""

    tool_calls_made: int
    """Number of tool calls the LLM made."""

    success: bool
    """Whether the LLM successfully completed the task."""

    error: Optional[str] = None
    """Error message if the task failed."""

    metadata: Optional[dict] = None
    """Additional provider-specific metadata."""


class LLMProvider(ABC):
    """Base interface for LLM providers that can generate MCP tool calls."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this provider."""
        pass

    @abstractmethod
    async def send_task(
        self, prompt: str, server_url: str, verbose: bool = False
    ) -> AsyncGenerator[str, None]:
        """Send a task to the LLM and yield progress messages.

        Args:
            prompt: The task prompt to send to the LLM
            server_url: The MCP server URL to use
            verbose: Whether to show detailed progress

        Yields
        ------
            Progress messages as the LLM works
        """
        pass

    @abstractmethod
    async def get_final_response(self) -> LLMResponse:
        """Get the final response after send_task completes.

        Returns
        -------
            LLMResponse with the results of the task
        """
        pass

    @abstractmethod
    async def cleanup(self):
        """Clean up any resources used by the provider."""
        pass
