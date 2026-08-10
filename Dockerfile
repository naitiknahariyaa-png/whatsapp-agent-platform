FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY agent-engine/requirements-render.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy all code
COPY agent-engine/ ./agent-engine/
COPY services/ ./services/
COPY frontend/ ./frontend/

# Set working directory
WORKDIR /app/agent-engine

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run the application
CMD ["python", "main.py"]