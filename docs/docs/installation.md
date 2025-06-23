---
sidebar_position: 3
---

# Installation

Detailed installation instructions for MCP Jupyter Server.

## Prerequisites

### 1. Install UV

UV is required for running MCP Jupyter. Install it using one of these methods:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or via pip
pip install uv
```

### 2. JupyterLab Setup

MCP Jupyter requires a running JupyterLab server with specific extensions:

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

<Tabs>
<TabItem value="venv" label="Using uv venv" default>

```bash
# Create virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install required packages
uv pip install jupyterlab jupyter-collaboration ipykernel

# Optional: Install additional packages
uv pip install numpy pandas matplotlib
```

</TabItem>
<TabItem value="project" label="Using uv project">

```bash
# Initialize a new project (if you don't have one)
uv init jupyter-workspace
cd jupyter-workspace

# Add required packages
uv add jupyterlab jupyter-collaboration ipykernel

# Optional: Add additional packages
uv add numpy pandas matplotlib
```

</TabItem>
</Tabs>

## Server Installation

### Using UV (Recommended)

The simplest way to use MCP Jupyter is via uvx:

```bash
uvx mcp-jupyter
```

This command will automatically download and run the latest version.

### From Source

For development or customization:

```bash
# Clone the repository
git clone https://github.com/block/mcp-jupyter.git
cd mcp-jupyter

# Sync all dependencies including dev tools
uv sync
```

## Starting the Jupyter Server

### Basic Setup

```bash
jupyter lab --port 8888 --IdentityProvider.token BLOCK --ip 0.0.0.0
```

### Custom Configuration

For production use or specific setups:

```bash
# Set custom token
export TOKEN=your-secure-token
jupyter lab --port 8888 --IdentityProvider.token $TOKEN

# Use config file
jupyter lab --config=/path/to/jupyter_config.py
```

## Client Configuration

### Goose

Add to your Goose session:

```bash
goose session --with-extension "uvx mcp-jupyter"
```

Or for development:

```bash
goose session --with-extension "uv run /path/to/mcp-jupyter/.venv/bin/mcp-jupyter"
```

### Cursor

Add to your MCP settings:

```json
{
  "mcpServers": {
    "jupyter": {
      "command": "uvx",
      "args": ["mcp-jupyter"],
      "env": {
        "TOKEN": "your-token-here"
      }
    }
  }
}
```

### Other MCP Clients

The general pattern for any MCP client:

```json
{
  "command": "uvx",
  "args": ["mcp-jupyter"],
  "stdio": true
}
```

## Troubleshooting

### Common Issues

1. **"Jupyter server is not accessible"**
   - Ensure Jupyter is running on the expected port
   - Check firewall settings
   - Verify the token matches

2. **"No kernel found"**
   - Make sure you have opened a notebook in Jupyter
   - Check that ipykernel is installed
   - Verify the notebook path is correct

3. **Package installation fails**
   - Ensure your virtual environment has pip
   - Check write permissions
   - Verify internet connectivity

### Debug Mode

Enable debug logging:

```bash
export MCP_JUPYTER_DEBUG=1
uvx mcp-jupyter
```

## Next Steps

- [Usage Guide →](/docs/usage)
- [Development Setup →](/docs/development)