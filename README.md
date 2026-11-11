# OmniExtract MCP & Apify Actor (`omni-extract-mcp`)

[![Apify Store](https://img.shields.io/badge/Apify_Store-poweragy%2Fomni--extract--mcp-00C853?logo=apify)](https://apify.com/poweragy/omni-extract-mcp)
[![MCP Protocol](https://img.shields.io/badge/MCP-2024--11--05-blue)](https://apify.com/poweragy/omni-extract-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Universal, Stateless, Cookie-Free Content & Transcript Extractor for AI Agents (Claude Desktop, Cursor, Windsurf, OpenClaw, n8n, Make, and Apify x402).**

👉 **Run Instantly in the Cloud (Zero Setup, Pay-Per-Result / x402 Ready)**: [**https://apify.com/poweragy/omni-extract-mcp**](https://apify.com/poweragy/omni-extract-mcp)

---

## Why OmniExtract?

Standard `WebFetch` and browser tools fail with `403 Forbidden`, login walls, or empty JavaScript shells when given social media or video URLs. **OmniExtract** converts complex links into clean, LLM-ready **Markdown + Timestamped Transcripts + Watermark-Free Media URLs** in one call:

1. **X (Twitter) Posts & Long-Form X Articles**: Full Draft.js block rendering (`# / ## / ###`, ordered/unordered lists, code blocks, blockquotes, quoted posts) and media extraction **with zero personal cookies required**.
2. **Douyin & TikTok Watermark-Free Extraction**: Pure-algorithm `x-secsdk-web-signature` signing (`ttwid` + `uifid` + MD5 salt) + 302 shortlink resolution + binary MIME magic sniffing (`WebP`/`JPEG`/`PNG`) — **zero headless browser overhead**.
3. **YouTube & Bilibili 3-Layer Subtitle Engine**: Extracts native & auto-generated VTT/SRT captions into deduplicated full-text transcripts and timestamped segments in ~2 seconds without downloading heavy video files.
4. **Anti-Bot Web & GitHub Markdown**: Automatic GitHub raw README/blob fast-path, semantic HTML-to-Markdown conversion, bot-wall detection, and Jina Reader fallback.

---

## Option 1: Hosted Cloud API & MCP via Apify Store (Recommended)

No local dependencies (`ffmpeg` / `yt-dlp`) or server maintenance required:

- **Apify Store Page**: [https://apify.com/poweragy/omni-extract-mcp](https://apify.com/poweragy/omni-extract-mcp)
- **REST API Call**:
  ```bash
  curl -X POST "https://api.apify.com/v2/acts/poweragy~omni-extract-mcp/run-sync-get-dataset-items?token=YOUR_APIFY_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "urls": [
        "https://x.com/ai_chuhai/status/2037437653071835440",
        "https://v.douyin.com/0kH2cQVrf0o/"
      ],
      "include_transcript": true
    }'
  ```

---

## Option 2: Local MCP Server (Claude Desktop / Cursor / Windsurf)

```bash
pip install git+https://github.com/solarfans/omni-extract-mcp.git
```

Add to your `claude_desktop_config.json` or `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "omni-extract": {
      "command": "python3",
      "args": ["-m", "omni_extract.mcp_server", "--mode", "stdio"]
    }
  }
}
```

### Exposed MCP Tools
- `omni_extract_url(url, include_transcript=True, output_format="markdown")`: Extract a single URL into structured Markdown or JSON.
- `omni_extract_batch(urls, include_transcript=True)`: Concurrently extract up to 10 URLs in parallel.
- `omni_check_quota(api_key="")`: Check remaining API key credits or daily quota.

---

## Option 3: Self-Hosted HTTP / Remote MCP Gateway

```bash
python3 -m omni_extract.mcp_server --mode http --port 8080
```

- `GET /v1/health`: Health & capability check
- `POST /mcp`: Streamable HTTP MCP JSON-RPC 2.0 endpoint
- `POST /v1/extract`: Direct REST single URL extraction
- `POST /v1/extract/batch`: Direct REST concurrent batch extraction
- `GET /v1/quota`: Check remaining API key credits or daily anonymous free quota
