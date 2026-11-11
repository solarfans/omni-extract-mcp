from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from apify_main import run_actor
from omni_extract.cache_and_billing import CacheAndBillingStore
from omni_extract.engine import OmniExtractEngine
from omni_extract.extractors.douyin_extractor import clean_short_title, detect_image_mime_ext
from omni_extract.extractors.video_extractor import parse_subtitle_content
from omni_extract.extractors.web_extractor import _SemanticMarkdownHTMLParser, is_valid_article_body
from omni_extract.extractors.x_extractor import _render_x_article_blocks
from omni_extract.mcp_server import handle_mcp_jsonrpc
from omni_extract.resolver import identify_target


class TestOmniExtract(unittest.TestCase):
    def test_zero_personal_path_or_credential_leakage(self) -> None:
        """Ensure the commercial codebase contains zero personal paths, cookies, or private API Bank references."""
        repo_root = Path(__file__).resolve().parent.parent
        forbidden_tokens = [
            "/Users/" + "kaykel",
            "API_BANK_DIR",
            ".x_likes_env",
            "com~apple~CloudDocs",
            "Iris/98_Melvin_Notes",
        ]
        checked_files = 0
        for ext in ("*.py", "*.json", "*.toml", "*.md"):
            for fpath in repo_root.rglob(ext):
                if "tests" in fpath.parts or ".git" in fpath.parts or "storage" in fpath.parts:
                    continue
                text = fpath.read_text(encoding="utf-8", errors="ignore")
                checked_files += 1
                for token in forbidden_tokens:
                    self.assertNotIn(token, text, f"Forbidden personal token {token!r} leaked in {fpath}")
        self.assertGreaterEqual(checked_files, 10)

    def test_resolver_identifies_all_platforms(self) -> None:
        t_x = identify_target("Check this out https://x.com/OpenAI/status/1895181715035160856?s=20", resolve_shortlinks=False)
        self.assertEqual(t_x.platform, "x")
        self.assertEqual(t_x.content_id, "1895181715035160856")
        self.assertNotIn("?", t_x.canonical_url)

        t_dy = identify_target(
            "4.66 复制打开抖音，看看【ClaudeCode提示缓存指南】 https://www.douyin.com/note/7703513872124769984?utm_source=copy",
            resolve_shortlinks=False,
        )
        self.assertEqual(t_dy.platform, "douyin")
        self.assertEqual(t_dy.content_type, "gallery")
        self.assertEqual(t_dy.content_id, "7703513872124769984")
        self.assertEqual(t_dy.title_hint, "ClaudeCode提示缓存指南")

        t_yt = identify_target("https://www.youtube.com/watch?v=dQw4w9WgXcQ", resolve_shortlinks=False)
        self.assertEqual(t_yt.platform, "youtube")
        self.assertEqual(t_yt.content_type, "video")
        self.assertEqual(t_yt.content_id, "dQw4w9WgXcQ")

        t_gh = identify_target("https://github.com/modelcontextprotocol/servers", resolve_shortlinks=False)
        self.assertEqual(t_gh.platform, "github")
        self.assertEqual(t_gh.content_type, "article")

    def test_x_article_blocks_markdown_rendering(self) -> None:
        article_payload = {
            "title": "How to Build High-Margin MCP Servers",
            "content": {
                "blocks": [
                    {"type": "header-one", "text": "Introduction"},
                    {"type": "unstyled", "text": "Agents need clean structured context."},
                    {"type": "header-two", "text": "Core Steps"},
                    {"type": "ordered-list-item", "text": "Solve a real anti-bot pain point"},
                    {"type": "ordered-list-item", "text": "Sell credit packs instead of subscriptions"},
                    {"type": "blockquote", "text": "Distribution beats complexity."},
                    {"type": "code-block", "text": "uvx omni-extract-mcp"},
                ]
            },
        }
        md = _render_x_article_blocks(article_payload)
        self.assertIn("# Introduction", md)
        self.assertIn("## Core Steps", md)
        self.assertIn("1. Solve a real anti-bot pain point", md)
        self.assertIn("2. Sell credit packs instead of subscriptions", md)
        self.assertIn("> Distribution beats complexity.", md)
        self.assertIn("```\nuvx omni-extract-mcp\n```", md)

    def test_douyin_magic_mime_and_title(self) -> None:
        self.assertEqual(detect_image_mime_ext(b"RIFF\x00\x00\x00\x00WEBPVP8 "), ("image/webp", "webp"))
        self.assertEqual(detect_image_mime_ext(b"\xff\xd8\xff\xe0\x00\x10JFIF"), ("image/jpeg", "jpeg"))
        self.assertEqual(detect_image_mime_ext(b"\x89PNG\r\n\x1a\n\x00\x00"), ("image/png", "png"))

        title = clean_short_title("全网最硬核的AI Agent抓取神器！#AI #编程 #黑科技", author="Melvin")
        self.assertEqual(title, "全网最硬核的AI Agent抓取神器")

    def test_vtt_subtitle_parser_deduplicates_and_segments(self) -> None:
        sample_vtt = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.500
<c>Hello world, welcome to OmniExtract.</c>

00:00:03.500 --> 00:00:05.000
Hello world, welcome to OmniExtract.

00:00:05.000 --> 00:00:08.250
This is the second unique sentence.
"""
        plain, segments = parse_subtitle_content(sample_vtt)
        self.assertEqual(
            plain.splitlines(),
            [
                "Hello world, welcome to OmniExtract.",
                "This is the second unique sentence.",
            ],
        )
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0], {"start": 1.0, "end": 3.5, "text": "Hello world, welcome to OmniExtract."})
        self.assertEqual(segments[1], {"start": 5.0, "end": 8.25, "text": "This is the second unique sentence."})

    def test_semantic_html_to_markdown_and_bot_wall_filter(self) -> None:
        html = """
        <html>
          <head><title>Deep Engineering Guide</title><script>alert(1)</script></head>
          <body>
            <nav>Menu</nav>
            <article>
              <h1>Deep Engineering Guide</h1>
              <p>This is a detailed paragraph with enough characters to pass the minimum length threshold for valid article extraction in production environments. We ensure that clean semantic HTML is converted into structured Markdown.</p>
              <ul><li>First bullet point</li><li>Second bullet point</li></ul>
            </article>
          </body>
        </html>
        """
        parser = _SemanticMarkdownHTMLParser()
        parser.feed(html)
        body = "".join(parser.md_parts).strip()
        self.assertIn("# Deep Engineering Guide", body)
        self.assertIn("- First bullet point", body)
        self.assertNotIn("alert(1)", body)
        self.assertTrue(is_valid_article_body(body, min_chars=100))
        self.assertFalse(is_valid_article_body("Just a moment... Verify you are human", min_chars=10))

    def test_cache_and_billing_quota_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "test_billing.sqlite3"
            store = CacheAndBillingStore(db_path=db_file, cache_ttl_seconds=3600, free_daily_limit=3)

            for i in range(3):
                res = store.consume_credits(credits=1, client_id="1.2.3.4", enforce=True)
                self.assertEqual(res["tier"], "free_daily")
                self.assertEqual(res["free_calls_remaining"], 2 - i)

            with self.assertRaises(PermissionError):
                store.consume_credits(credits=1, client_id="1.2.3.4", enforce=True)

            api_key = store.mint_api_key(credits=500, owner_email="buyer@example.com")
            self.assertTrue(api_key.startswith("omni_live_"))

            q1 = store.check_quota(api_key=api_key)
            self.assertTrue(q1["valid"])
            self.assertEqual(q1["credits_remaining"], 500)

            c_paid = store.consume_credits(credits=5, api_key=api_key, enforce=True)
            self.assertEqual(c_paid["credits_remaining"], 495)

            sample_payload = {
                "url": "https://x.com/test/status/123",
                "canonical_url": "https://x.com/i/status/123",
                "platform": "x",
                "content_type": "article",
                "content_id": "123",
                "title": "Test",
                "author": "@test",
                "text": "Hello",
                "markdown": "# Test\n\nHello",
                "transcript": None,
                "segments": [],
                "media_urls": [],
                "cover_url": None,
                "duration_seconds": 0.0,
                "extraction_tier": "fxtwitter",
                "credits_charged": 1,
                "cache_hit": False,
                "metadata": {},
            }
            store.set_cached("https://x.com/i/status/123", "x", sample_payload)
            cached = store.get_cached("https://x.com/i/status/123")
            self.assertIsNotNone(cached)
            assert cached is not None
            self.assertTrue(cached["cache_hit"])
            self.assertEqual(cached["title"], "Test")

    def test_mcp_jsonrpc_protocol_and_apify_actor_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "mcp_test.sqlite3"
            engine = OmniExtractEngine(db_path=db_file, enforce_billing=False)

            seeded_url = "https://x.com/i/status/999888777"
            engine.store.set_cached(
                seeded_url,
                "x",
                {
                    "url": seeded_url,
                    "canonical_url": seeded_url,
                    "platform": "x",
                    "content_type": "article",
                    "content_id": "999888777",
                    "title": "Seeded X Article",
                    "author": "AI Researcher (@ai_res)",
                    "text": "Full 5,000-word X Article body extracted cleanly.",
                    "markdown": "# Seeded X Article\n\nFull 5,000-word X Article body extracted cleanly.",
                    "transcript": None,
                    "segments": [],
                    "media_urls": [],
                    "cover_url": None,
                    "duration_seconds": 0.0,
                    "extraction_tier": "fxtwitter_graphql_cookie_free",
                    "credits_charged": 1,
                    "cache_hit": False,
                    "metadata": {"is_x_article": True},
                },
            )

            init_resp = handle_mcp_jsonrpc(engine, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            self.assertIsNotNone(init_resp)
            assert init_resp is not None
            self.assertEqual(init_resp["result"]["serverInfo"]["name"], "omni-extract-mcp")

            list_resp = handle_mcp_jsonrpc(engine, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            self.assertIsNotNone(list_resp)
            assert list_resp is not None
            tool_names = [t["name"] for t in list_resp["result"]["tools"]]
            self.assertIn("omni_extract_url", tool_names)
            self.assertIn("omni_extract_batch", tool_names)
            self.assertIn("omni_check_quota", tool_names)

            call_resp = handle_mcp_jsonrpc(
                engine,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "omni_extract_url",
                        "arguments": {"url": seeded_url, "output_format": "markdown"},
                    },
                },
            )
            self.assertIsNotNone(call_resp)
            assert call_resp is not None
            self.assertFalse(call_resp["result"]["isError"])
            self.assertIn("Full 5,000-word X Article body", call_resp["result"]["content"][0]["text"])

            storage_dir = Path(tmp) / "apify_storage"
            old_db = os.environ.get("OMNI_DB_PATH")
            old_storage = os.environ.get("APIFY_LOCAL_STORAGE_DIR")
            try:
                os.environ["OMNI_DB_PATH"] = str(db_file)
                os.environ["APIFY_LOCAL_STORAGE_DIR"] = str(storage_dir)

                actor_results = run_actor({"urls": [seeded_url], "include_transcript": True, "use_cache": True})
                self.assertEqual(len(actor_results), 1)
                self.assertTrue(actor_results[0]["ok"])
                self.assertEqual(actor_results[0]["apify_ppe_event"], "content_item_extracted")
                ds_file = storage_dir / "datasets" / "default" / "000000001.json"
                self.assertTrue(ds_file.is_file())
                saved_item = json.loads(ds_file.read_text(encoding="utf-8"))
                self.assertEqual(saved_item["title"], "Seeded X Article")
            finally:
                if old_db is None:
                    os.environ.pop("OMNI_DB_PATH", None)
                else:
                    os.environ["OMNI_DB_PATH"] = old_db
                if old_storage is None:
                    os.environ.pop("APIFY_LOCAL_STORAGE_DIR", None)
                else:
                    os.environ["APIFY_LOCAL_STORAGE_DIR"] = old_storage


if __name__ == "__main__":
    unittest.main()
