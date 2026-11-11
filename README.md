# OmniExtract MCP & Apify Actor (`omni-extract-mcp`)

**Universal, Stateless, Cookie-Free Content & Transcript Extractor for AI Agents (Claude Desktop, Cursor, Windsurf, OpenClaw, n8n, Apify x402).**

Stop feeding `403 Forbidden` or empty JavaScript shells to your LLM agents. `OmniExtract` turns complex social & video links into clean, structured **Markdown + Timestamped Transcripts + Watermark-Free Media URLs** in one call:

- **X (Twitter) Posts & Long-Form X Articles**: Full Draft.js block rendering (`# / ## / ###`, lists, code blocks, quotes) and media extraction **with zero personal cookies required**.
- **Douyin & TikTok Watermark-Free Extraction**: Pure-algorithm `x-secsdk-web-signature` signing (`ttwid` + `uifid` + MD5 salt) + 302 shortlink resolution + binary MIME magic sniffing (`WebP`/`JPEG`/`PNG`) — **zero headless browser overhead**.
- **YouTube & Bilibili 3-Layer Subtitle Engine**: Extracts native & auto-generated VTT/SRT captions into deduplicated full-text transcripts and timestamped segments in ~2 seconds without downloading heavy video files.
- **Anti-Bot Web & GitHub Markdown**: Automatic GitHub raw README/blob fast-path, semantic HTML-to-Markdown conversion, bot-wall detection, and Jina Reader fallback.

---

## Quick Start (MCP Server for Claude Desktop / Cursor / Windsurf)

```json
{
  "mcpServers": {
    "omni-extract": {
      "command": "python3",
      "args": ["-m", "omni_extract.mcp_server", "--mode", "stdio"],
      "env": {
        "OMNI_API_KEY": "omni_live_optional_paid_key"
      }
    }
  }
}
```

### Exposed MCP Tools
1. `omni_extract_url(url, include_transcript=True, output_format="markdown")`
2. `omni_extract_batch(urls, include_transcript=True)`
3. `omni_check_quota(api_key="")`

---

## Cloud HTTP & Remote MCP Mode (GCP Cloud Run / Smithery)

```bash
python3 -m omni_extract.mcp_server --mode http --port 8080 --enforce-billing
```

- `GET /v1/health`: Health & capability check
- `POST /mcp`: Streamable HTTP MCP JSON-RPC 2.0 endpoint
- `POST /v1/extract`: Direct REST single URL extraction
- `POST /v1/extract/batch`: Direct REST concurrent batch extraction
- `GET /v1/quota`: Check remaining API key credits or daily anonymous free quota
