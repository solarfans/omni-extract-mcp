# Fix: YouTube Transcript Blocked or Empty Subtitles on Cloud/Server IPs

Extracting YouTube transcripts on cloud servers (Docker, GCP, AWS, Apify) often fails due to datacenters hitting YouTube bot-check interstitials or returning empty XML/VTT caption tracks.

## Multi-Tier Transcript Fallback in OmniExtract MCP
`omni_extract_url(..., include_transcript=true)` runs a 3-layer caption pipeline that falls back across native player caption APIs, `yt-dlp` subtitle dumps, and VTT/SRT timestamp deduplication (`[{"start": ..., "end": ..., "text": ...}]`), returning clean LLM-ready Markdown without downloading gigabytes of MP4 streams.

```bash
curl -X POST "https://api.apify.com/v2/acts/poweragy~omni-extract-mcp/run-sync-get-dataset-items?token=YOUR_APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"], "include_transcript": true}'
```

- Hosted Apify Store Actor ($5 / 1k results, 24h dedup cache): `https://apify.com/poweragy/omni-extract-mcp`
- Hosted Streamable MCP URL: `https://mcp.apify.com/?actors=poweragy/omni-extract-mcp`
