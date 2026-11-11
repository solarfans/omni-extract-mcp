FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md apify_main.py ./
COPY omni_extract ./omni_extract
COPY .actor ./.actor

RUN pip install --no-cache-dir --upgrade pip yt-dlp && \
    pip install --no-cache-dir -e .

EXPOSE 8080

# Smart entrypoint:
# - If running inside Apify Actor batch job (APIFY_IS_AT_HOME=1 and not standby HTTP), run apify_main.py
# - Otherwise start the HTTP/MCP gateway on $PORT (for GCP Cloud Run, Smithery, or Apify Standby MCP)
CMD ["sh", "-c", "if [ \"$APIFY_IS_AT_HOME\" = \"1\" ] && [ \"$APIFY_META_ORIGIN\" != \"STANDBY\" ]; then python3 apify_main.py; else python3 -m omni_extract.mcp_server --mode http --port ${PORT:-8080}; fi"]
