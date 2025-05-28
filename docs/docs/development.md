---
sidebar_position: 5
---

# Development

Set up MCP Jupyter for development and contribution.

## Development Setup

### 1. Clone the Repository

```bash
mkdir ~/Development
cd ~/Development
git clone https://github.com/squareup/mcp-jupyter.git
cd mcp-jupyter
```

### 2. Create Development Environment

```bash
# Create virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode
uv pip install -e .

# Install development dependencies
uv pip install pytest pytest-asyncio ruff mypy
```

### 3. Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=mcp_jupyter

# Run specific test file
pytest tests/test_notebook.py
```

## Using Development Version

### With Goose

For development, use the local installation:

```bash
goose session --with-extension "uv run $(pwd)/.venv/bin/mcp-jupyter"
```

This allows you to make changes and test them immediately by restarting Goose.

### With Other Clients

Update your MCP configuration to point to your local installation:

```json
{
  "mcpServers": {
    "jupyter": {
      "command": "/path/to/mcp-jupyter/.venv/bin/python",
      "args": ["-m", "mcp_jupyter"],
      "env": {
        "PYTHONPATH": "/path/to/mcp-jupyter"
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
│   ├── test_notebook.py
│   ├── test_integration.py
│   └── test_notebook_paths.py
├── demos/
│   ├── demo.ipynb
│   └── goose-demo.png
├── pyproject.toml
└── README.md
```

## Making Changes

### Code Style

We use `ruff` for linting and formatting:

```bash
# Format code
ruff format .

# Check linting
ruff check .

# Fix linting issues
ruff check --fix .
```

### Type Checking

Run mypy for type checking:

```bash
mypy src/mcp_jupyter
```

### Testing Changes

1. **Unit Tests**: Test individual functions
2. **Integration Tests**: Test with real Jupyter server
3. **Manual Testing**: Test with your MCP client

Example test:

```python
def test_notebook_creation():
    """Test creating a new notebook."""
    notebook_path = "test_notebook.ipynb"
    cells = ["import pandas as pd", "print('Hello, World!')"]
    
    create_new_notebook(notebook_path, cells, server_url, token)
    
    assert check_notebook_exists(notebook_path, server_url, token)
```

## Debugging

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

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

### Common Issues

1. **Import errors**: Ensure you're in the virtual environment
2. **Connection issues**: Check Jupyter server is running
3. **State issues**: Clear notebook state and restart kernel

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
pytest

# Check formatting
ruff format --check .

# Check types
mypy src/mcp_jupyter
```

### 4. Submit PR

1. Push to your fork
2. Create pull request
3. Describe changes clearly
4. Link any related issues

## Architecture

### Key Components

1. **MCP Server** (`server.py`)
   - Handles MCP protocol
   - Manages tool registration
   - Routes requests

2. **Notebook Manager** (`notebook.py`)
   - Creates/manages notebooks
   - Handles kernel lifecycle
   - Manages sessions

3. **State Tracker** (`state.py`)
   - Tracks notebook state
   - Manages state consistency
   - Provides decorators

4. **Jupyter Client** (`jupyter.py`)
   - Communicates with Jupyter
   - Handles authentication
   - Manages connections

### Adding New Tools

To add a new MCP tool:

```python
@mcp.tool()
def my_new_tool(param1: str, param2: int = 10) -> dict:
    """Tool description for MCP clients.
    
    Args:
        param1: Description of param1
        param2: Description of param2
        
    Returns:
        dict: Result of the operation
    """
    # Implementation
    return {"result": "success"}
```

## Next Steps

- [Usage Guide →](/docs/usage)
- [Installation →](/docs/installation)