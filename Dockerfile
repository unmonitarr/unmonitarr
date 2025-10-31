FROM python:3.12-slim

WORKDIR /app

# System deps (optional but useful for CA certs, curl, tzdata)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata procps curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/

# Ensure src is importable
ENV PYTHONPATH=/app/src

# Default command runs the main application
CMD ["python", "src/main.py"]