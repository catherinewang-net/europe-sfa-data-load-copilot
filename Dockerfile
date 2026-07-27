# Europe SFA Data Load Copilot — leadership demo container
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=true \
    DEPLOYMENT_MODE=demo \
    METADATA_MODE=bundled \
    BUNDLED_METADATA_PATH=/app/bundled_metadata \
    PORT=8501

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fail fast if bundled metadata is missing or contains forbidden files
RUN python scripts/audit_bundled_metadata.py --bundle-dir /app/bundled_metadata

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python scripts/healthcheck.py || exit 1

CMD ["sh", "-c", "streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT} --server.headless=true"]
