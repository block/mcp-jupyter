# Jupyter MCP Server

> **⚠️ API Compatibility Notice**: This project is currently focused on MCP (Model Context Protocol) usage. There are **no API compatibility guarantees** between versions as the interface is actively evolving. Breaking changes may occur in any release.

Jupyter MCP Server allows you to use tools like [Goose](https://block.github.io/goose/) or Cursor to pair with you in a JupyterLab notebook where the state of your variables, etc is preserved by the JupyterLab Kernel.  The fact that state is preserved is the key to this because it allows to to pair with the Agent in a notebook, where for example if a package is not installed it will see the error and install it for you.   You as the user can then do some data exploration and then hand off to the agent at any time to pick up where you left off.

## Key Features

- **4 Consolidated MCP Tools** (reduced from 11):
  - `query_notebook` - All read-only operations (view source, check server, etc.)
  - `modify_notebook_cells` - All cell modifications (add, edit, delete cells)
  - `execute_notebook_code` - All execution operations (run cells, install packages)
  - `setup_notebook` - Notebook initialization and kernel connection
- **Workflow-oriented design** optimized for AI agent collaboration
- **State preservation** across notebook sessions
- **Automatic parameter validation** with float-to-int conversion

This works with any client that supports MCP but will focus on using Goose for the examples.

## Requirements
You will need [UV](https://docs.astral.sh/uv/) is required to be installed. 

## Installation
This MCP server supports multiple transport modes and can be added to client with the command `uvx mcp-jupyter`.

### Transport Modes

The server supports two transport protocols:
- **stdio** (default) - Standard input/output communication
- **http** - Streamable HTTP transport with session management

To use a specific transport:
```bash
# Default stdio transport
uvx mcp-jupyter

# HTTP transport on custom port (stateful - maintains session)
uvx mcp-jupyter --transport http --port 8080

# HTTP transport in stateless mode (no session persistence)
uvx mcp-jupyter --transport http --port 8080 --stateless-http
```

### Using HTTP Transport with Cursor

To connect Cursor to an HTTP MCP server:

1. Start the server separately:
```bash
uvx mcp-jupyter --transport http --port 8090
```

2. Configure Cursor's `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "notebook-http": {
      "url": "http://localhost:8090/mcp/"  // ⚠️ Trailing slash is REQUIRED
    }
  }
}
```

**Important:** The trailing slash (`/mcp/`) is required for Cursor to connect properly to the HTTP endpoint.

## Usage

### Start Jupyter
The server expects that a server is already running on a port that is available to the client. If the environmental variable TOKEN is not set, it will default to "BLOCK". The server requires that jupyter-collaboration and ipykernel are installed.

**Option 1: Using uv venv**
```bash
# Create virtual environment  
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install Jupyter dependencies
uv pip install jupyterlab jupyter-collaboration ipykernel

# Start Jupyter
jupyter lab --port 8888 --IdentityProvider.token BLOCK --ip 0.0.0.0
```

**Option 2: Using uv project**
```bash
# Initialize project (if you don't have one)
uv init jupyter-workspace && cd jupyter-workspace

# Install Jupyter dependencies
uv add jupyterlab jupyter-collaboration ipykernel

# Start Jupyter
uv run jupyter lab --port 8888 --IdentityProvider.token BLOCK --ip 0.0.0.0
```

### Goose Usage

Here's a demonstration of the tool in action:

![MCP Jupyter Demo](demos/goose-demo.png) 

You can view the Generated notebook here: [View Demo Notebook](demos/demo.ipynb)

## Development
Steps remain similar except you will need to clone this mcp-jupyter repository and use that for the server instead of the precompiled version.

### MCP Server

1. Clone and setup the repository:
```bash
mkdir ~/Development
cd ~/Development
git clone https://github.com/block/mcp-jupyter.git
cd mcp-jupyter

# Sync all dependencies
uv sync
```

Using editable mode allows you to make changes to the server and only have you need to restart Goose, etc.
`goose session --with-extension "uv run --directory $(pwd) mcp-jupyter"`
