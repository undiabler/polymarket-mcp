# PolyMarket MCP Server

Opinionated Model Context Protocol (MCP) server for large-scale agentic integrations with the PolyMarket API. 
This server provides **smart** tools for LLM agents to search, navigate, and filter interesting events. 
This MCP server is NOT designed and will NOT be able to perform actual bets. The sole purpose is to provide relevant data for exploration.
Actual participation (account management) is a separate responsibility that should not be mixed with this project.
The server is designed for remote use and easy connection to most of [MCP clients](https://modelcontextprotocol.io/clients). 

## Motivation
This project is the third iteration of tools that were developed to automate Polymarket betting using LLMs with human feedback.
The first few iterations very quickly faced environment limitations because they were designed for specific use cases. This third iteration overcomes all previously faced problems and is designed to be simultaneously integrated in a universal way into different environments: Claude, OpenCode, ChatGPT, PydanticAI, n8n, etc. It provides tools with limited responsibility but a very high level of abstraction.

## Features

- **In-memory cache**: All Polymarket events loaded at startup for instant queries
- **Background daemon**: Automatic updates (incremental fetch, refresh stale, cleanup expired)
- **Events first**: Events are the primary entity (stop overbetting on the same event)
- **Global analytics**: Total liquidity, market counts, distribution metrics
- **Combined filtering**: Search by liquidity, expiry, tags, profit potential
- **Remote MCP**: Run on server and connect to existing online clients.

## Installation and Usage

This system was designed to run remotely, making Docker the ideal standard for packaging the project without worrying about dependencies. Docker also enables easy horizontal scaling by running multiple container instances.

### Quick Start (Remote Build)

Build directly from GitHub on your remote server:

```bash
docker build -t polymarket-mcp https://github.com/undiabler/polymarket-mcp.git
```

### Local Build

Alternatively, clone the repository and build locally:

```bash
git clone https://github.com/undiabler/polymarket-mcp.git
cd polymarket-mcp
docker build -t polymarket-mcp .
```

### Running the Server

Once the Docker image is built, run the container:

```bash
docker run -d -p 8000:8000 --name polymarket-mcp-app \
  -e MCP_BEARER_TOKEN=<your generated key to secure> \
  --volume polycache:/app/data \
  polymarket-mcp
```

That's it! Your MCP server is now running and accessible at `http://your-server-ip:8000` as an endpoint for MCP clients.
You can also skip --volume flag, but your application will start slow since it will load all events on statrup. Mounted volume preserve cache between restarts.

### Environment Variables
No additional Polymarket API keys are required to make public data requests.
- `MCP_BEARER_TOKEN` - Bearer token for securing your MCP and API endpoints (required, can be any string)