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