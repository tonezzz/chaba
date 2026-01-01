FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8340

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl docker.io \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir \
      fastapi \
      httpx \
      mcp \
      python-dotenv \
      python-on-whales \
      pyyaml \
      "uvicorn[standard]"

COPY . .

EXPOSE 8340

ENV PYTHONPATH=/app/src

CMD ["sh", "-c", "uvicorn docker_mcp.http_server:create_app --host 0.0.0.0 --port ${PORT:-8340}"]
