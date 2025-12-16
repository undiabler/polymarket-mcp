# Perplexity MCP Server - Docker Image
FROM python:3.11-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml README.md ./

# Install dependencies (frozen from lock file)
# RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY main.py ./
COPY src/ ./src/

# Install the project itself
RUN uv sync --no-dev

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Default port
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000
EXPOSE 8000

# Run the server (--no-sync since deps installed at build time)
CMD ["uv", "run", "--no-sync", "python", "main.py"]

