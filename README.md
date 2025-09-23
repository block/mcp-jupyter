# Jupyter MCP Server

> **⚠️ API Compatibility Notice**: This project is currently focused on MCP (Model Context Protocol) usage. There are **no API compatibility guarantees** between versions as the interface is actively evolving. Breaking changes may occur in any release.

Jupyter MCP Server allows you to use tools like [Goose](https://block.github.io/goose/) or Cursor to pair with you in a JupyterLab notebook where the state of your variables is preserved by the JupyterLab Kernel. This enables seamless collaboration where agents can install packages, fix errors, and hand off to you for data exploration at any time.

**Architecture**: Uses Jupyter's REST API for reliable agent operations while maintaining real-time user synchronization through RTC. See [Architecture Documentation](docs/docs/architecture.md) for detailed technical information.

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
- **stdio** (default) - Standard input/output communication, ideal for local IDE integrations
- **http** - Streamable HTTP transport with session management, enabling serverless deployments and remote access

#### Use Cases for HTTP Transport
- **Serverless deployments**: Host the MCP server in cloud environments (AWS Lambda, Google Cloud Functions, etc.)
- **Remote access**: Connect to the server from different machines or networks
- **Web integrations**: Build web-based AI assistants that connect to the MCP server
- **Stateless operations**: Use `--stateless-http` for environments where session persistence isn't needed

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

## LLM Evaluation

This project includes a comprehensive testing infrastructure for validating how well different LLMs can generate MCP tool calls from natural language prompts.

### Test Architecture

The LLM testing system uses a pluggable provider architecture:

- **`LLMProvider`**: Abstract base class that all providers implement
- **`LLMResponse`**: Standardized response format with success metrics and metadata
- **Parameterized tests**: Same test runs against all available providers

### Current Providers

- **ClaudeCodeProvider**: Uses the Claude Code SDK (no API key required)

### Running LLM Tests

```bash
# Run LLM tool call generation tests
uv run pytest -m llm -v

# See LLM working in real-time (shows detailed progress)
uv run pytest -m llm -v -s

# Run all tests except LLM tests (default behavior)
uv run pytest -v
```

### What the Tests Validate

Each LLM provider is tested on its ability to:

1. **Understand natural language prompts** about Jupyter notebook tasks
2. **Generate correct MCP tool calls** (`query_notebook`, `setup_notebook`, `modify_notebook_cells`)
3. **Successfully execute the calls** to create notebooks with expected content
4. **Handle errors gracefully** when operations fail

### Adding New Providers

To add a new LLM provider:

1. **Implement the interface**:
```python
# tests/llm_providers/my_llm.py
from .base import LLMProvider, LLMResponse

class MyLLMProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "my-llm"

    async def send_task(self, prompt: str, server_url: str, verbose: bool = False):
        # Implement LLM interaction
        pass

    async def get_final_response(self) -> LLMResponse:
        # Return standardized response
        pass

    async def cleanup(self):
        # Clean up resources
        pass
```

2. **Update configuration**:
```python
# tests/llm_providers/config.py - add to get_available_providers()
if os.getenv("MY_LLM_API_KEY"):
    from .my_llm import MyLLMProvider
    providers.append(MyLLMProvider())
```

3. **Test automatically**: Your provider will be included in parameterized tests when its environment variables are set.

This infrastructure makes it easy to validate and compare how different LLMs perform at generating MCP tool calls for Jupyter notebook automation.
