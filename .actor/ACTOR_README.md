# Douyin (抖音) & X (Twitter) Article to Markdown Scraper (MCP & x402 Ready)

Extract **full long-form X (Twitter) Articles & Threads**, **watermark-free Douyin (抖音) & TikTok videos/photo galleries**, **Xiaohongshu (RedNote) notes**, **YouTube/Bilibili transcripts with timestamps**, and **anti-bot web articles** into clean, LLM-ready **Markdown + Structured JSON** in one call.

- **Zero Cookies or Login Required**: Pure-algorithm `x-secsdk-web-signature` signing for Douyin (`v.douyin.com`) and GraphQL extraction for X Articles — no account ban risk, no proxy setup required.
- **50%+ Cheaper Than Single-Platform Scrapers**: Just **$0.005 per extracted item ($5.00 / 1,000 results)** with automatic 24h deduplication cache.
- **Built for AI Agents, MCP, n8n, Make & Obsidian**: Returns both clean `markdown` (ready for LLM context windows or Obsidian vaults) and structured metadata (`media_urls`, `transcript`, `segments`, engagement counts).

---

## Supported Platforms & Capabilities

| Platform | URL Examples | What You Get |
| :--- | :--- | :--- |
| **Douyin (抖音)** | `https://v.douyin.com/...`<br>`https://www.douyin.com/video/...`<br>`https://www.douyin.com/note/...` | **Watermark-free MP4 stream URLs**, high-res gallery images (`JPEG`/`PNG`/`WebP`), full caption, author info, likes/saves/comments/shares. |
| **X (Twitter) Articles & Posts** | `https://x.com/user/status/...`<br>`https://twitter.com/user/status/...` | **Full 10,000+ word X Articles** rendered with `# / ##` headings, lists, code blocks & blockquotes, NoteTweets, quoted tweets, media URLs, and engagement stats. |
| **YouTube & Bilibili (哔哩哔哩)** | `https://www.youtube.com/watch?v=...`<br>`https://www.bilibili.com/video/BV...` | Video metadata, cover image, full deduplicated **plain-text transcript**, and **timestamped subtitle segments** (`[{"start": 1.0, "end": 3.5, "text": "..."}]`). |
| **TikTok & Xiaohongshu (小红书 / RedNote)** | `https://vt.tiktok.com/...`<br>`https://www.xiaohongshu.com/explore/...` | Post title, full note text/caption, author details, and media/image URLs. |
| **GitHub & Anti-Bot Web** | `https://github.com/owner/repo`<br>Any blog, news, or documentation URL | Clean semantic Markdown stripped of ads, navbars, scripts, and Cloudflare bot-wall noise. |

---

## Input Parameters

```json
{
  "urls": [
    "https://x.com/ai_chuhai/status/2037437653071835440",
    "https://v.douyin.com/0kH2cQVrf0o/",
    "https://github.com/modelcontextprotocol/servers"
  ],
  "include_transcript": true,
  "use_cache": true
}
```

- **`urls`** *(array of strings, required)*: List of URLs or raw mobile share texts (e.g. `"4.66 复制打开抖音... https://v.douyin.com/..."`).
- **`include_transcript`** *(boolean, default: `true`)*: Extract full video subtitles and timestamped segments for YouTube/Bilibili/TikTok videos.
- **`use_cache`** *(boolean, default: `true`)*: Instant `<5ms` response if the same URL was extracted within the last 24 hours.

---

## Output Example (Dataset Item)

```json
{
  "ok": true,
  "url": "https://v.douyin.com/0kH2cQVrf0o/",
  "canonical_url": "https://www.douyin.com/note/7703513872124769984",
  "platform": "douyin",
  "content_type": "gallery",
  "content_id": "7703513872124769984",
  "title": "ClaudeCode最该开的设置",
  "author": "AI进化论",
  "text": "Claude Code 提示缓存 TTL 配置指南...",
  "markdown": "# ClaudeCode最该开的设置\n\n- **Platform**: Douyin (gallery)\n- **Author**: AI进化论\n...",
  "transcript": null,
  "segments": [],
  "media_urls": [
    "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/..."
  ],
  "cover_url": "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/...",
  "duration_seconds": 0.0,
  "extraction_tier": "douyin_sec_salt_md5_signature",
  "metadata": {
    "aweme_id": "7703513872124769984",
    "digg_count": 1420,
    "collect_count": 890,
    "comment_count": 64
  }
}
```

---

## Use with AI Agents (MCP) & Automation (n8n / Make / cURL)

### 1. Synchronous REST API Call (Get Markdown in 1 HTTP Request)
```bash
curl -X POST "https://api.apify.com/v2/acts/poweragy~omni-extract-mcp/run-sync-get-dataset-items?token=YOUR_APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://x.com/ai_chuhai/status/2037437653071835440"]
  }'
```

### 2. Use via Apify MCP Server (Claude Desktop / Cursor / Windsurf)
Connect `poweragy/omni-extract-mcp` directly to your AI Agent via `https://mcp.apify.com/?actors=poweragy/omni-extract-mcp`!
