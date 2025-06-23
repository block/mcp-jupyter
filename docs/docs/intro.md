---
sidebar_position: 1
slug: /
---

# Introduction

MCP Jupyter Server allows you to use AI assistants like [Goose](https://block.github.io/goose/) or Cursor to pair with you in JupyterLab notebooks where the state of your variables is preserved by the JupyterLab Kernel.

## Why MCP Jupyter?

The key advantage of MCP Jupyter is **state preservation**. This allows you to:

- Work with your AI assistant in a notebook where variables and data remain intact
- Let the AI see errors and install missing packages automatically
- Do data exploration yourself, then hand off to the agent to continue
- Maintain context throughout your entire session

## How It Works

MCP Jupyter acts as a bridge between MCP-compatible AI clients and your JupyterLab server:

```
AI Client (Goose/Cursor) <--> MCP Jupyter Server <--> JupyterLab Kernel
                                                           |
                                                      Preserved State
                                                    (Variables/Data)
```

This architecture ensures that your notebook state is maintained throughout the session, enabling seamless collaboration between you and your AI assistant.

## Key Features

- **State Preservation**: Variables and data persist across interactions
- **Error Handling**: AI can see and respond to errors in real-time
- **Package Management**: Automatic package installation when needed
- **Seamless Handoff**: Switch between manual and AI-assisted work anytime
- **MCP Protocol**: Works with any MCP-compatible client
- **Optimized Architecture**: 4 consolidated tools following MCP best practices
- **Workflow-oriented Design**: Tools match AI collaboration patterns vs API endpoints

## Next Steps

- [Quickstart Guide →](/docs/quickstart)
- [Installation →](/docs/installation)
- [Architecture →](/docs/architecture)
- [Usage Examples →](/docs/usage)