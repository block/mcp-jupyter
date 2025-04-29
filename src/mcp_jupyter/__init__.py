import argparse

from .server import mcp


def main():
    """MCP Jupyter: Control a Jupyter notebook from MCP."""
    parser = argparse.ArgumentParser(
        description="Gives you the ability to control a Jupyter notebook from MCP."
    )
    parser.parse_args()
    mcp.run()


if __name__ == "__main__":
    main()
