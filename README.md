# Jupyter MCP Server

Jupyter MCP Server allows you to use tools like [Goose](https://block.github.io/goose/) or Cursor to pair with you in a JupyterLab notebook where the state of your variables, etc is preserved by the Jupterlab Kernel.  The fact that state is preserved is the key to this because it allows to to pair with the Agent in a notebook, where for example if a package is not installed it will see the error and install it for you.   You as the user can then do some data exploration and then hand off to the agent at any time to pick up where you left off.




  This works with any client that supports MCP but will focus on using Goose for the examples.

## Requirements
You will need [UV](https://docs.astral.sh/uv/) is required to be installed. 

## Installation
This MCP server uses stdio and can been added to client with the command `uvx mcp-jupyter`.  

## Usage

### Start Jupyter
The server expects that a server is already running on a port that is available to the client.   If the environmental variable TOKEN is not set, it will default to "BLOCK".  The server requires that jupyter-collaboration and ipykernel are installed. An example setup is below.

```bash
uv venv
source .venv/bin/activate
uv pip install jupyterlab jupyter-collaboration ipykernel
jupyter lab --port 8888 --IdentityProvider.token BLOCK --ip 0.0.0.0
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
cd mcp-server

uv venv
source .venv/bin/activate
uv pip install -e .
```

Using editable mode allows you to make changes to the server and only have you need to restart Goose, etc.
`goose session --with-extension "uv run $(pwd)/.venv/bin/mcp-jupyter"`
