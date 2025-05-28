---
sidebar_position: 2
---

# Quickstart

Get up and running with MCP Jupyter in minutes.

## Requirements

- [UV](https://docs.astral.sh/uv/) - Required for installation
- JupyterLab with `jupyter-collaboration` and `ipykernel`
- An MCP-compatible client (e.g., [Goose](https://block.github.io/goose/), Cursor)

## Installation

MCP Jupyter Server uses stdio and can be added to any MCP client with:

```bash
uvx mcp-jupyter
```

## Quick Setup

### 1. Start Jupyter Server

First, set up and start your Jupyter server:

```bash
# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install jupyterlab jupyter-collaboration ipykernel

# Start Jupyter server
jupyter lab --port 8888 --IdentityProvider.token BLOCK --ip 0.0.0.0
```

:::tip
The server expects a token for authentication. If the `TOKEN` environment variable is not set, it defaults to "BLOCK".
:::

### 2. Configure Your MCP Client

#### For Goose

Add MCP Jupyter to your Goose configuration:

```bash
goose session --with-extension "uvx mcp-jupyter"
```

#### For Other Clients

Add the following to your MCP client configuration:

```json
{
  "mcpServers": {
    "jupyter": {
      "command": "uvx",
      "args": ["mcp-jupyter"]
    }
  }
}
```

### 3. Start Using

Once configured, you can:

1. Create or open a notebook through your AI assistant
2. Execute code cells with preserved state
3. Let the AI handle errors and install packages
4. Switch between manual and AI-assisted work seamlessly

## Example Session

```python
# Your AI assistant can help you:
# 1. Load and explore data
# 2. Visualize results
# 3. Debug errors
# 4. Install missing packages
# All while preserving your notebook state!
```

## Next Steps

- [Detailed Installation Guide →](/docs/installation)
- [Usage Examples →](/docs/usage)
- [Development Setup →](/docs/development)