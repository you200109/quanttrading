FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy vc requirements and install
COPY vigilant-couscous/requirements.txt ./vc-requirements.txt
RUN pip install --no-cache-dir -r vc-requirements.txt 2>/dev/null || true

# Copy application code
COPY . .

# Expose ports
EXPOSE 8000 8001

# Environment variables
ENV API_HOST=0.0.0.0
ENV API_PORT=8000
ENV OKX_DEMO=true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
