"""
Polymarket MCP Server - Entry Point

Runs FastAPI server with:
- MCP tools mounted at /mcp/
- REST API endpoints at /api/
PolyStorage lifecycle handled via FastAPI lifespan.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api_routes import router as api_router
from src.mcp_tools import mcp
from src.poly_storage import PolyStorage

# Server configuration from environment
HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8000"))

# Create MCP http app first (needed for lifespan integration)
mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Combined lifespan context manager for FastAPI.

    Handles:
    - MCP's StreamableHTTPSessionManager initialization
    - PolyStorage async startup and shutdown
    """
    storage = PolyStorage.get_instance()

    # Run MCP lifespan alongside our storage lifespan
    async with mcp_app.lifespan(app):
        # Startup: load data and start daemon
        await storage.start()

        try:
            yield
        finally:
            # Shutdown: stop daemon gracefully
            await storage.stop()
            print("Server stopped.")


# Create FastAPI app with combined lifespan
app = FastAPI(
    title="Polymarket MCP Server",
    description="MCP tools and REST API for Polymarket integration",
    lifespan=lifespan,
)

# Include REST API routes
app.include_router(api_router, prefix="/api")

# Mount MCP server
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    import uvicorn

    print(f"Starting Polymarket MCP Server on {HOST}:{PORT}...")
    uvicorn.run(app, host=HOST, port=PORT)
