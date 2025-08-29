import argparse
import logging

from .server import create_server

logger = logging.getLogger(__name__)


def main():
    """MCP Jupyter: Control a Jupyter notebook from MCP."""
    parser = argparse.ArgumentParser(
        description="Gives you the ability to control a Jupyter notebook from MCP."
    )
    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport type to use (default: stdio)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        help="Enable stateless HTTP mode (no session persistence)",
    )

    args = parser.parse_args()

    # Create the server with appropriate settings
    if args.transport == "http":
        logger.info(
            f"Starting MCP server on {args.host}:{args.port} with HTTP transport"
        )
        server = create_server(
            host=args.host, port=args.port, stateless_http=args.stateless_http
        )
        server.run(transport="streamable-http")
    else:
        logger.info(f"Starting MCP server with stdio transport")
        server = create_server()
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
