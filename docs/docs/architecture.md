---
sidebar_position: 5
---

# Architecture

Understanding the design and structure of MCP Jupyter.

## Tool Design

MCP Jupyter uses **4 consolidated tools** (reduced from 11):

### 1. `query_notebook` - Read Operations
All read-only operations for querying notebook information:
- `view_source` - View cell source code (single cell or all)
- `check_server` - Check if Jupyter server is accessible  
- `list_sessions` - List all notebook sessions
- `get_position_index` - Get cell index by execution count or cell ID

Uses `query_type` parameter to specify which operation to perform.

### 2. `modify_notebook_cells` - Cell Operations  
All cell modification operations:
- `add_code` - Add and optionally execute code cells
- `edit_code` - Edit existing code cells
- `add_markdown` - Add markdown cells
- `edit_markdown` - Edit existing markdown cells
- `delete` - Delete cells

Uses `operation` parameter to specify which action to perform.

### 3. `execute_notebook_code` - Execution Operations
All code execution operations:
- `execute_cell` - Execute existing code cells
- `install_packages` - Install packages using uv pip

Uses `execution_type` parameter to specify the type of execution.

### 4. `setup_notebook` - Initialization
Notebook setup and kernel connection:
- Creates new notebooks if needed
- Connects to existing kernels
- Manages notebook sessions

## Key Components

### 1. MCP Server (`server.py`)
- Handles MCP protocol with consolidated tools
- Manages parameter routing and validation
- Provides float-to-int conversion for position_index
- Routes requests to appropriate internal functions

### 2. Notebook Manager (`notebook.py`)
- Creates and manages notebooks on Jupyter server
- Handles kernel lifecycle management
- Manages notebook sessions
- Handles directory creation for nested paths

### 3. State Tracker (`state.py`)
- Tracks notebook state changes
- Manages state consistency between operations
- Provides decorators:
  - `@state_dependent` - Validates state before operations
  - `@refreshes_state` - Updates state after operations

### 4. Jupyter Integration (`jupyter.py`)
- Low-level Jupyter server communication
- WebSocket connections for real-time updates
- Authentication token management

### 5. Utilities (`utils.py`)
- Helper functions for path handling
- Parameter extraction and validation
- File extension management (.ipynb)

## Data Flow

```
AI Client → MCP Server → Tool Router → Internal Function → Jupyter Server
                ↓
        Parameter Validation
                ↓
        State Management
                ↓
        Response Formatting
```

## State Management

MCP Jupyter maintains notebook state consistency through:

1. **State Hashing** - Tracks changes to notebook content
2. **Dependency Decorators** - Ensures operations use current state
3. **Server URL Tracking** - Maps notebooks to their Jupyter servers
4. **Kernel Management** - Maintains kernel connections

## Adding New Operations

To extend functionality, add new operations to existing tools:

```python
# In query_notebook
if query_type == "my_new_query":
    return _query_my_new_operation(notebook_path, **kwargs)

# In modify_notebook_cells  
if operation == "my_new_operation":
    return _modify_my_new_operation(notebook_path, **kwargs)
```

## Error Handling

- **Parameter Validation** - Type checking and conversion
- **Connection Errors** - Jupyter server connectivity issues
- **State Mismatches** - Notebook state inconsistencies  
- **Execution Failures** - Kernel execution problems

All errors provide actionable messages to help users recover.