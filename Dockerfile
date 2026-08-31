# ---- Builder stage: install Python deps ----
FROM python:3.14-slim-bookworm AS builder

ENV PATH="/opt/venv/bin:$PATH" \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN python -m venv /opt/venv

WORKDIR /build
COPY pyproject.toml .
RUN uv pip install --python /opt/venv/bin/python --no-cache -r pyproject.toml


# ---- Runtime stage ----
FROM python:3.14-slim-bookworm

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bring in the installed dependencies from the builder
COPY --from=builder /opt/venv /opt/venv

# Application code
COPY agent-engine/ ./agent-engine/
COPY services/ ./services/

RUN mkdir -p /app/agent-engine/data && chmod 755 /app/agent-engine/data

# Observability: emit structured (JSON) logs by default in containers
ENV LOG_FORMAT=json \
    LOG_LEVEL=info

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Workers = (2 x CPU cores) + 1 for I/O bound apps
CMD ["uvicorn", "agent-engine.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--no-access-log", \
     "--log-level", "info"]
