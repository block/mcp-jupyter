"""Configuration for LLM providers in testing."""

import os
from typing import Any, Dict, List

from .base import LLMProvider
from .claude_code import ClaudeCodeProvider


def get_available_providers() -> List[LLMProvider]:
    """Get list of available LLM providers based on configuration and environment.

    Returns
    -------
        List of available LLM providers
    """
    providers = []

    # Claude Code is always available since it doesn't require API keys
    providers.append(ClaudeCodeProvider())

    # Future providers can be added here with environment checks when implemented

    return providers


def get_provider_config() -> Dict[str, Any]:
    """Get configuration for LLM providers.

    Returns
    -------
        Configuration dictionary
    """
    return {
        "timeout_seconds": int(os.getenv("LLM_TEST_TIMEOUT", "300")),
        "max_retries": int(os.getenv("LLM_TEST_MAX_RETRIES", "3")),
        "providers": {
            "claude-code": {
                "enabled": True,
                "requires_api_key": False,
            }
        },
    }


def get_test_providers() -> List[LLMProvider]:
    """Get providers that should be used in tests.

    This respects environment variables to enable/disable specific providers.

    Returns
    -------
        List of providers to test
    """
    config = get_provider_config()
    available = get_available_providers()

    # Filter based on configuration
    enabled_provider_names = [
        name
        for name, provider_config in config["providers"].items()
        if provider_config["enabled"]
    ]

    return [
        provider for provider in available if provider.name in enabled_provider_names
    ]
