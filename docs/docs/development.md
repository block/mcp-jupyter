---
sidebar_position: 6
---

# Development

Set up MCP Jupyter for development and contribution.

## Development Setup

### 1. Clone the Repository

```bash
mkdir ~/Development
cd ~/Development
git clone https://github.com/block/mcp-jupyter.git
cd mcp-jupyter
```

### 2. Create Development Environment

```bash
# Sync all dependencies including dev tools
uv sync
```

### 3. Run Tests

```bash
# Run all tests
uv run pytest tests/

# Run with coverage
uv run pytest --cov=mcp_jupyter tests/

# Run specific test file
uv run pytest tests/test_integration.py

# Run LLM tool call generation tests
uv run pytest -m llm -v

# Run all tests except LLM tests (default behavior)
uv run pytest -v
```

## Using Development Version

### With Goose

For development, use the local installation:

```bash
goose session --with-extension "uv run --directory $(pwd) mcp-jupyter"
```

This allows you to make changes and test them immediately by restarting Goose.

### With Other Clients

Update your MCP configuration to point to your local installation:

```json
{
  "mcpServers": {
    "jupyter": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-jupyter", "mcp-jupyter"],
      "env": {
        "TOKEN": "your-token-here"
      }
    }
  }
}
```

## Project Structure

```
mcp-jupyter/
├── src/
│   └── mcp_jupyter/
│       ├── __init__.py
│       ├── __main__.py       # Entry point
│       ├── server.py         # MCP server implementation
│       ├── notebook.py       # Notebook operations
│       ├── jupyter.py        # Jupyter integration
│       ├── state.py          # State management
│       └── utils.py          # Utilities
├── tests/
│   ├── test_integration.py   # Integration tests with real Jupyter server
│   ├── test_notebook_paths.py # Unit tests for notebook path handling
│   ├── test_llm_tool_calls.py # LLM tool call generation tests
│   └── llm_providers/        # LLM provider architecture
│       ├── base.py           # Base provider interface
│       ├── claude_code.py    # Claude Code provider
│       └── config.py         # Provider configuration
├── demos/
│   ├── demo.ipynb
│   └── goose-demo.png
├── docs/                     # Documentation site
├── pyproject.toml
└── README.md
```

## Making Changes

### Code Style

We use `ruff` for linting and formatting:

```bash
# Format code
uv run ruff format .

# Check linting
uv run ruff check .

# Fix linting issues
uv run ruff check --fix .
```

### Testing Changes

1. **Unit Tests**: Test individual functions
2. **Integration Tests**: Test with real Jupyter server
3. **LLM Tests**: Test how well LLMs generate MCP tool calls
4. **Manual Testing**: Test with your MCP client

Example test:

```python
def test_notebook_creation():
    """Test creating a new notebook."""
    notebook_path = "test_notebook.ipynb"
    cells = ["import pandas as pd", "print('Hello, World!')"]

    create_new_notebook(notebook_path, cells, server_url, token)

    assert check_notebook_exists(notebook_path, server_url, token)
```

### LLM Evaluation

The project includes comprehensive testing for how well different LLMs can generate MCP tool calls from natural language prompts.

#### Test Architecture

- **Pluggable providers**: Easy to add new LLMs (Claude Code, Gemini, OpenAI, etc.)
- **Standardized interface**: All providers implement the same `LLMProvider` interface
- **Parameterized tests**: Same test validates all providers consistently
- **Real-time monitoring**: Watch LLMs generate tool calls with verbose output

#### Running LLM Tests

```bash
# Run LLM tool call generation tests
uv run pytest -m llm -v

# See LLM working in real-time (shows detailed progress)
uv run pytest -m llm -v -s

# Test specific provider
uv run pytest -k "claude-code" -m llm -v
```

#### What Gets Tested

Each LLM provider is validated on:

1. **Understanding natural language prompts** about Jupyter tasks
2. **Generating correct MCP tool calls** (`query_notebook`, `setup_notebook`, etc.)
3. **Successfully executing the calls** to create notebooks with expected content
4. **Error handling** when operations fail

#### Adding New LLM Providers

1. **Create provider class** in `tests/llm_providers/`:
```python
class MyLLMProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "my-llm"

    async def send_task(self, prompt: str, server_url: str, verbose: bool = False):
        # Implement LLM interaction
        pass

    async def get_final_response(self) -> LLMResponse:
        # Return results with success metrics
        pass
```

2. **Update configuration** in `tests/llm_providers/config.py`:
```python
if os.getenv("MY_LLM_API_KEY"):
    from .my_llm import MyLLMProvider
    providers.append(MyLLMProvider())
```

3. **Test automatically**: Provider included when environment variables are set

This makes it easy to validate and compare how different LLMs perform at MCP tool call generation.

## Debugging

### Using VS Code

1. Create `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Debug MCP Jupyter",
      "type": "python",
      "request": "launch",
      "module": "mcp_jupyter",
      "justMyCode": true,
      "env": {
        "PYTHONPATH": "${workspaceFolder}",
        "TOKEN": "BLOCK"
      }
    }
  ]
}
```

2. Set breakpoints in the code
3. Run with F5


## Contributing

### 1. Fork and Branch

```bash
git checkout -b feature/your-feature-name
```

### 2. Make Changes

- Follow the code style
- Add tests for new features
- Update documentation

### 3. Test Thoroughly

```bash
# Run tests
uv run pytest tests/

# Check formatting
uv run ruff format --check .

# Check types
uv run mypy src/mcp_jupyter
```

### 4. Submit PR

1. Push to your fork
2. Create pull request
3. Describe changes clearly
4. Link any related issues

## Next Steps

- [Architecture →](/docs/architecture)
- [Usage Guide →](/docs/usage)
- [Installation →](/docs/installation)
