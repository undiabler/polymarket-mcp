"""
Polymarket MCP Server - Entry Point

Runs FastMCP server for LLM agent integration.
PolyStorage lifecycle (daemon, disk loading) handled via lifespan in mcp_tools.
"""

import os
from src.mcp_tools import mcp

# Server configuration from environment
HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8000"))


def run():
    """Entry point for script."""
    print(f"Starting Polymarket MCP Server on {HOST}:{PORT}...")
    # mcp.run(transport="sse", host=HOST, port=PORT)
    mcp.run(transport="streamable-http", host=HOST, port=PORT)



if __name__ == "__main__":
    run()

