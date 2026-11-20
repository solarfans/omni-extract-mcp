# Fix: X (Twitter) Article & Post Scraping Returns Truncated Preview or JS Shell

Standard `curl`, `WebFetch`, or headless scrapers often hit an empty JavaScript shell (`"JavaScript is not available"`) or only receive a 280-character preview when reading long-form X Articles (`x.com/<user>/status/<id>`).

## Root Cause
Long-form X Articles store structured paragraphs, headings, ordered lists, code blocks, and embedded images inside Draft.js entity maps (`article.content.blocks` / `entityMap`), which plain HTML parsers cannot render without hydration.

## Cookie-Free Fix with OmniExtract MCP
`omni_extract_url` resolves syndication/GraphQL payloads natively without browser cookies and compiles Draft.js blocks into structured Markdown (`#`, `##`, fenced code blocks, and image captions).

### Via Apify Cloud / Remote MCP
```bash
curl -X POST "https://api.apify.com/v2/acts/poweragy~omni-extract-mcp/run-sync-get-dataset-items?token=YOUR_APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://x.com/user/status/1234567890"], "include_transcript": true}'
```

### Via Local MCP (`stdio`)
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
